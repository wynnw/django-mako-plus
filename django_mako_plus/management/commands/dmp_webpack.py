from django.apps import apps as django_apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django_mako_plus.template import create_mako_context
from django_mako_plus.provider.runner import ProviderRun, init_provider_factories
from django_mako_plus.management.mixins import DMPCommandMixIn
from mako.template import Template as MakoTemplate

import sys
import os
import os.path
from collections import OrderedDict
from datetime import datetime



class Command(DMPCommandMixIn, BaseCommand):
    help = 'Removes compiled template cache folders in your DMP-enabled app directories.'
    can_import_settings = True


    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument(
            '--overwrite',
            action='store_true',
            dest='overwrite',
            default=False,
            help='Overwrite existing __entry__.js if necessary'
        )
        parser.add_argument(
            '--single',
            type=str,
            metavar='FILENAME',
            help='Instead of per-app entry files, create a single file that includes the JS for all listed apps'
        )
        parser.add_argument(
            'appname',
            type=str,
            nargs='*',
            help='The name of one or more DMP apps. If omitted, all DMP apps are processed'
        )


    def handle(self, *args, **options):
        dmp = django_apps.get_app_config('django_mako_plus')
        self.options = options
        self.factories = init_provider_factories('WEBPACK_PROVIDERS')

        # ensure we have a base directory
        try:
            if not os.path.isdir(os.path.abspath(settings.BASE_DIR)):
                raise CommandError('Your settings.py BASE_DIR setting is not a valid directory.  Please check your settings.py file for the BASE_DIR variable.')
        except AttributeError as e:
            raise CommandError('Your settings.py file is missing the BASE_DIR setting.')

        # the apps to process
        apps = []
        for appname in options.get('appname'):
            apps.append(django_apps.get_app_config(appname))
        if len(apps) == 0:
            apps = dmp.get_registered_apps()

        # main runner for per-app files
        if options.get('single') is None:
            for app in apps:
                self.message('Searching `{}` app...'.format(app.name))
                filename = os.path.join(app.path, 'scripts', '__entry__.js')
                self.create_entry_file(filename, self.generate_script_map(app), [ app ])

        # main runner for one sitewide file
        else:
            script_map = {}
            for app in apps:
                self.message('Searching `{}` app...'.format(app.name))
                script_map.update(self.generate_script_map(app))
            self.create_entry_file(options.get('single'), script_map, apps)


    def create_entry_file(self, filename, script_map, apps):
        '''Creates an entry file for the given script map'''
        # delete previous file if it exists, and ensure the target directory is there
        if os.path.exists(filename):
            if self.options.get('overwrite'):
                os.remove(filename)
            else:
                raise CommandError('Refusing to destroy existing file: {} (use --overwrite option or remove the file)'.format(filename))
        if not os.path.exists(os.path.dirname(filename)):
            os.makedirs(os.path.dirname(filename))

        # prune the script_map to the apps we are bundling
        def in_apps(s):
            for app in apps:
                last = None
                path = os.path.dirname(s)
                while last != path:
                    if os.path.samefile(app.path, path):
                        return True
                    last = path
                    path = os.path.dirname(last)
            return False
        pruned_script_map = {}
        for key in script_map.keys():
            pruned_paths = [ path for path in script_map[key] if in_apps(path) ]
            if len(pruned_paths) > 0:
                pruned_script_map[key] = pruned_paths
        if len(pruned_script_map) == 0:
            return

        # write the entry file
        self.message('Creating {}'.format(os.path.relpath(filename, settings.BASE_DIR)))
        template = MakoTemplate('''
<%! from datetime import datetime %>
<%! import sys %>
<%! import os %>

// Generated on ${ datetime.now().strftime('%Y-%m-%d %H:%M') } by `${ ' '.join(sys.argv) }`
// Contains links for ${ 'app' if len(apps) == 1 else 'apps' }: ${ ', '.join(sorted([ a.name for a in apps ])) }

(context => {
  %for (app, template), script_paths in script_map.items():
    DMP_CONTEXT.setTemplateFunction("${ app }/${ template }", () => {
      %for path in script_paths:
        require("./${ os.path.relpath(path, os.path.dirname(filename)) }");
      %endfor
    })
  %endfor
})(DMP_CONTEXT.get());
''')
        with open(filename, 'w') as fout:
            fout.write(template.render(
                apps=apps,
                script_map=pruned_script_map,
                filename=filename,
            ).strip())



    def generate_script_map(self, config):
        '''
        Maps templates in this app to their scripts.  This function deep searches
        app/templates/* for the templates of this app.  Returns the following
        dictionary with absolute paths:

        {
            ( 'appname', 'template1' ): [ '/abs/path/to/scripts/template1.js', '/abs/path/to/scripts/supertemplate1.js' ],
            ( 'appname', 'template2' ): [ '/abs/path/to/scripts/template2.js', '/abs/path/to/scripts/supertemplate2.js', '/abs/path/to/scripts/supersuper2.js' ],
            ...
        }

        Any files or subdirectories starting with double-underscores (e.g. __dmpcache__) are skipped.
        '''
        script_map = OrderedDict()
        template_root = os.path.join(os.path.relpath(config.path, settings.BASE_DIR), 'templates')
        def recurse(folder):
            subdirs = []
            if os.path.exists(folder):
                for filename in os.listdir(folder):
                    if filename.startswith('__'):
                        continue
                    filerel = os.path.join(folder, filename)
                    if os.path.isdir(filerel):
                        subdirs.append(filerel)

                    elif os.path.isfile(filerel):
                        template_name = os.path.relpath(filerel, template_root)
                        scripts = self.template_scripts(config, template_name)
                        key = ( config.name, os.path.splitext(template_name)[0] )
                        self.message('Found template: {}; static files: {}'.format(key, scripts), 3)
                        if len(scripts) > 0:
                            script_map[key] = scripts
            for subdir in subdirs:
                recurse(subdir)

        recurse(template_root)
        return script_map


    def template_scripts(self, config, template_name):
        '''
        Returns a list of scripts used by the given template object AND its ancestors.

        This runs a ProviderRun on the given template (as if it were being displayed).
        This allows the WEBPACK_PROVIDERS to provide the JS files to us.

        For this algorithm to work, the providers must extend static_links.LinkProvider
        because that class creates the 'enabled' list of provider instances, and each
        provider instance has a url.
        '''
        dmp = django_apps.get_app_config('django_mako_plus')
        template_obj = dmp.engine.get_template_loader(config, create=True).get_mako_template(template_name, force=True)
        mako_context = create_mako_context(template_obj)
        inner_run = ProviderRun(mako_context['self'], factories=self.factories)
        inner_run.run()
        scripts = []
        for data in inner_run.column_data:
            for provider in data.get('enabled', []):    # if file doesn't exist, the provider won't be enabled
                if hasattr(provider, 'filepath'):       # providers used to collect for webpack must have a .filepath property
                    scripts.append(provider.filepath)   # the absolute path to the file (see providers/static_links.py)
        return scripts
