from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
import os
import os.path
import shutil
import collections
import logging
from .base import BaseProvider
from ..util import log
from ..command import run_command


PREVIOUS_SOURCEPATH_KEY = '_previous_sourcepaths_'



class CompileProvider(BaseProvider):
    '''
    Runs a command, such as compiling *.scss or *.less, when an output file
    timestamp is older than the source file.

    When settings.DEBUG=True, checks for a recompile every request.
    When settings.DEBUG=False, checks for a recompile only once per server run.
    '''
    DEFAULT_OPTIONS = {
        'group': 'styles',

        # source path to search for, relative to the project directory.  possible values are:
        #   1. None: a default path is used, such as "{app}/{subdir}/{filename.ext}", prefixed
        #      with the static root at production; see subclasses for their default filenames.
        #   2. function, lambda, or other callable: called as func(provider) and
        #      should return a string
        #   3. str: used directly
        'sourcepath': None,

        # target path to search for, relative to the project directory.  possible values are:
        # should resolve to one exact file. possible values:
        #   1. None: a default path is used, such as "{app}/{subdir}/{filename.ext}", prefixed
        #      with the static root at production; see subclasses for their default filenames.
        #   2. function, lambda, or other callable: called as func(provider) and
        #      should return a string
        #   3. str: used directly
        'targetpath': None,

        # explicitly sets the command to be run. possible values:
        #   1. None or []: the default command is run
        #   2. function, lambda, or other callable: called as func(provider), expects list as return
        #   3. list: used directly in the call to subprocess module
        'command': [],

        # set of sourcepaths we've previously checked for compilation - for internal use only
        # I'm using the options for this because this dictionary is unique to this exact provider and
        # its options. The provider class is NOT unique because the same provider can be listed more
        # than once in settings.
        PREVIOUS_SOURCEPATH_KEY: set(),
    }


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sourcepath = os.path.join(settings.BASE_DIR if settings.DEBUG else settings.STATIC_ROOT, self.build_sourcepath())
        self.targetpath = os.path.join(settings.BASE_DIR if settings.DEBUG else settings.STATIC_ROOT, self.build_targetpath())
        # do we need to compile?
        if not settings.DEBUG and self.sourcepath in self.options[PREVIOUS_SOURCEPATH_KEY]:
            do_compile, msg = False, 'checked earlier'
        elif not os.path.exists(self.sourcepath):
            do_compile, msg = False, 'nonexistent file'
        elif not self.needs_compile:
            do_compile, msg = False, 'already up-to-date'
        else:
            do_compile, msg = True, 'compiling'
        if log.isEnabledFor(logging.DEBUG):
            log.debug('%s created for %s [%s]', repr(self), self.sourcepath, msg)
        # do the compile
        if do_compile:
            if not os.path.exists(os.path.dirname(self.targetpath)):
                os.makedirs(os.path.dirname(self.targetpath))
            run_command(*self.build_command())
        # record that we've checked this template
        self.options[PREVIOUS_SOURCEPATH_KEY].add(self.sourcepath)

    def build_sourcepath(self):
        # if defined in settings, run the function or return the string
        if self.options['sourcepath'] is not None:
            return self.options['sourcepath'](self) if callable(self.options['sourcepath']) else self.options['sourcepath']
        # build the default
        if self.app_config is None:
            log.warn('{} skipped: template %s not in project subdir and `targetpath` not in settings', (self.__class__.__qualname__, self.template_relpath))
        return self.build_default_sourcepath()

    def build_default_sourcepath(self):
        # this method is overridden in CompileScssProvider and CompileLessProvider lower in this file
        raise ImproperlyConfigured('{} must set `sourcepath` in options (or a subclass can override build_default_sourcepath).'.format(self.__class__.__qualname__))

    def build_targetpath(self):
        # if defined in settings, run the function or return the string
        if self.options['targetpath'] is not None:
            return self.options['targetpath'](self) if callable(self.options['targetpath']) else self.options['targetpath']
        # build the default
        if self.app_config is None:
            log.warn('{} skipped: template %s not in project subdir and `targetpath` not in settings', (self.__class__.__qualname__, self.template_relpath))
        return self.build_default_targetpath()

    def build_default_targetpath(self):
        # this method is overridden in CompileScssProvider and CompileLessProvider lower in this file
        raise ImproperlyConfigured('{} must set `targetpath` in options (or a subclass can override build_default_targetpath).'.format(self.__class__.__qualname__))

    def build_command(self):
        '''Returns the command to run, as a list (see subprocess module)'''
        # if defined in settings, run the function or return the string
        if self.options['command']:
            return self.options['command'](self) if callable(self.options['command']) else self.options['command']
        # build the default
        return self.build_default_command()

    def build_default_command(self):
        # this method is overridden in CompileScssProvider and CompileLessProvider lower in this file
        raise ImproperlyConfigured('{} must set `command` in options (or a subclass can override build_default_command).'.format(self.__class__.__qualname__))

    @property
    def needs_compile(self):
        '''Returns True if self.sourcepath is newer than self.targetpath'''
        try:
            source_mtime = os.stat(self.sourcepath).st_mtime
        except OSError:  # no source for this template, so just return
            return False
        try:
            target_mtime = os.stat(self.targetpath).st_mtime
        except OSError: # target doesn't exist, so compile
            return True
        # both source and target exist, so compile if source newer
        return source_mtime > target_mtime


###################
###   Sass

class CompileScssProvider(CompileProvider):
    '''Specialized CompileProvider for SCSS'''
    def build_default_sourcepath(self):
        return os.path.join(
            self.app_config.name,
            'styles',
            self.template_relpath + '.scss',
        )

    def build_default_targetpath(self):
        # posixpath because URLs use forward slash
        return os.path.join(
            self.app_config.name,
            'styles',
            self.template_relpath + '.css',
        )

    def build_default_command(self):
        return [
            shutil.which('sass'),
            '--source-map',
            '--load-path={}'.format(settings.BASE_DIR),
            self.sourcepath,
            self.targetpath,
        ]


#####################
###   Less

class CompileLessProvider(CompileProvider):
    '''Specialized CompileProvider that contains settings for *.less files.'''
    def build_default_sourcepath(self):
        return os.path.join(
            self.app_config.name,
            'styles',
            self.template_relpath + '.less',
        )

    def build_default_targetpath(self):
        # posixpath because URLs use forward slash
        return os.path.join(
            self.app_config.name,
            'styles',
            self.template_relpath + '.css',
        )

    def build_default_command(self):
        return [
            shutil.which('lessc'),
            '--source-map',
            self.sourcepath,
            self.targetpath,
        ]
