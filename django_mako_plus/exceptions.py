from django.http import HttpResponse, Http404, HttpResponseRedirect, HttpResponsePermanentRedirect




###############################################################
###   Exceptions used to direct the controller


class InternalRedirectException(Exception):
    '''View functions can throw this exception to indicate that a new view
       should be called by the HtmlPageServer.  The current view function
       will end immediately, and processing will be passed to the new view function.
    '''
    def __init__(self, redirect_module, redirect_function):
        '''Indicates the new view to be called.  The view should be given relative to the project root.
           The parameters should be strings, not the actual module or function reference.
        '''
        super(InternalRedirectException, self).__init__()
        self.redirect_module = redirect_module
        self.redirect_function = redirect_function




class RedirectException(Exception):
    '''Immediately stops processing of a view function or template and redirects to the given page.
       Perhaps it takes a little too much liberty with exceptions, but it makes returning from a
       huge call stack really nice.

       If as_javascript==True, the browser is sent <script>window.location.href="...";</script>.
       This is useful when using Ajax.  A redirect in Ajax is handled internally by libraries like
       JQuery, so a regular HTTP redirect can't direct the top-level page.  Javascript is a hack
       around this so an Ajax call can redirect the whole browser window.
    '''
    def __init__(self, redirect_to, permanent=False, as_javascript=False):
        self.redirect_to = redirect_to
        self.permanent = permanent
        self.as_javascript = as_javascript


    def get_response(self, request):
        '''Returns the redirect response for this exception.  DMP passes the current request
           as a parameter for your convenience in using the user object, session object, etc.'''
        if self.as_javascript:
            return HttpResponse('<script>window.location.href="%s";</script>' % self.redirect_to)
        if self.permanent:
            return HttpResponsePermanentRedirect(self.redirect_to)
        return HttpResponseRedirect(self.redirect_to)
