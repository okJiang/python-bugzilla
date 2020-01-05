# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from logging import getLogger
import sys

# pylint: disable=import-error
if sys.version_info[0] >= 3:
    from xmlrpc.client import Fault, ProtocolError, ServerProxy, Transport
else:
    from xmlrpclib import Fault, ProtocolError, ServerProxy, Transport
# pylint: enable=import-error

from requests import RequestException

from ._backendbase import _BackendBase
from .exceptions import BugzillaError
from ._util import listify


log = getLogger(__name__)


class _BugzillaXMLRPCTransport(Transport):
    def __init__(self, bugzillasession):
        if hasattr(Transport, "__init__"):
            Transport.__init__(self, use_datetime=False)

        self.__bugzillasession = bugzillasession
        self.__bugzillasession.set_content_type("text/xml")
        self.__seen_valid_xml = False

        # Override Transport.user_agent
        self.user_agent = self.__bugzillasession.get_user_agent()


    ############################
    # Bugzilla private helpers #
    ############################

    def __request_helper(self, url, request_body):
        """
        A helper method to assist in making a request and parsing the response.
        """
        response = None
        # pylint: disable=try-except-raise
        try:
            session = self.__bugzillasession.get_requests_session()
            response = session.post(url, data=request_body)

            # We expect utf-8 from the server
            response.encoding = 'UTF-8'

            # update/set any cookies
            self.__bugzillasession.set_response_cookies(response)

            response.raise_for_status()
            return self.parse_response(response)
        except RequestException as e:
            if not response:
                raise
            raise ProtocolError(
                url, response.status_code, str(e), response.headers)
        except Fault:
            raise
        except Exception:
            msg = str(sys.exc_info()[1])
            if not self.__seen_valid_xml:
                msg += "\nThe URL may not be an XMLRPC URL: %s" % url
            e = BugzillaError(msg)
            # pylint: disable=attribute-defined-outside-init
            e.__traceback__ = sys.exc_info()[2]
            # pylint: enable=attribute-defined-outside-init
            raise e


    ######################
    # Tranport overrides #
    ######################

    def parse_response(self, response):
        """
        Override Transport.parse_response
        """
        parser, unmarshaller = self.getparser()
        msg = response.text.encode('utf-8')
        try:
            parser.feed(msg)
        except Exception:
            log.debug("Failed to parse this XMLRPC response:\n%s", msg)
            raise

        self.__seen_valid_xml = True
        parser.close()
        return unmarshaller.close()

    def request(self, host, handler, request_body, verbose=0):
        """
        Override Transport.request
        """
        # Setting self.verbose here matches overrided request() behavior
        # pylint: disable=attribute-defined-outside-init
        self.verbose = verbose

        url = "%s://%s%s" % (self.__bugzillasession.get_scheme(),
                host, handler)

        # xmlrpclib fails to escape \r
        request_body = request_body.replace(b'\r', b'&#xd;')

        return self.__request_helper(url, request_body)


class _BugzillaXMLRPCProxy(ServerProxy, object):
    """
    Override of xmlrpc ServerProxy, to insert bugzilla API auth
    into the XMLRPC request data
    """
    def __init__(self, uri, bugzillasession, *args, **kwargs):
        self.__bugzillasession = bugzillasession
        transport = _BugzillaXMLRPCTransport(self.__bugzillasession)
        ServerProxy.__init__(self, uri, transport, *args, **kwargs)

    def _ServerProxy__request(self, methodname, params):
        """
        Overrides ServerProxy _request method
        """
        if len(params) == 0:
            params = ({}, )

        log.debug("XMLRPC call: %s(%s)", methodname, params[0])
        api_key = self.__bugzillasession.get_api_key()
        token_value = self.__bugzillasession.get_token_value()

        if api_key is not None:
            if 'Bugzilla_api_key' not in params[0]:
                params[0]['Bugzilla_api_key'] = api_key
        elif token_value is not None:
            if 'Bugzilla_token' not in params[0]:
                params[0]['Bugzilla_token'] = token_value

        # pylint: disable=no-member
        ret = ServerProxy._ServerProxy__request(self, methodname, params)
        # pylint: enable=no-member

        if isinstance(ret, dict) and 'token' in ret.keys():
            self.__bugzillasession.set_token_value(ret.get('token'))
        return ret


class _BackendXMLRPC(_BackendBase):
    """
    Internal interface for direct calls to bugzilla's XMLRPC API
    """
    def __init__(self, url, bugzillasession):
        _BackendBase.__init__(self, bugzillasession)
        self._xmlrpc_proxy = _BugzillaXMLRPCProxy(url, self._bugzillasession)

    def get_xmlrpc_proxy(self):
        return self._xmlrpc_proxy

    def bugzilla_version(self):
        return self._xmlrpc_proxy.Bugzilla.version()
    def bugzilla_extensions(self):
        return self._xmlrpc_proxy.Bugzilla.extensions()

    def bug_attachment_get(self, attachment_ids, paramdict):
        data = paramdict.copy()
        data["attachment_ids"] = listify(attachment_ids)
        return self._xmlrpc_proxy.Bug.attachments(data)
    def bug_attachment_get_all(self, bug_ids, paramdict):
        data = paramdict.copy()
        data["ids"] = listify(bug_ids)
        return self._xmlrpc_proxy.Bug.attachments(data)
    def bug_attachment_create(self, paramdict):
        return self._xmlrpc_proxy.Bug.add_attachment(paramdict)
    def bug_attachment_update(self, paramdict):
        return self._xmlrpc_proxy.Bug.update_attachment(paramdict)

    def bug_comments(self, paramdict):
        return self._xmlrpc_proxy.Bug.comments(paramdict)
    def bug_create(self, paramdict):
        return self._xmlrpc_proxy.Bug.create(paramdict)
    def bug_fields(self, paramdict):
        return self._xmlrpc_proxy.Bug.fields(paramdict)
    def bug_get(self, paramdict):
        return self._xmlrpc_proxy.Bug.get(paramdict)
    def bug_history(self, paramdict):
        return self._xmlrpc_proxy.Bug.history(paramdict)
    def bug_legal_values(self, paramdict):
        return self._xmlrpc_proxy.Bug.legal_values(paramdict)
    def bug_search(self, paramdict):
        return self._xmlrpc_proxy.Bug.search(paramdict)
    def bug_update(self, paramdict):
        return self._xmlrpc_proxy.Bug.update(paramdict)
    def bug_update_tags(self, paramdict):
        return self._xmlrpc_proxy.Bug.update_tags(paramdict)

    def component_create(self, paramdict):
        return self._xmlrpc_proxy.Component.create(paramdict)
    def component_update(self, paramdict):
        return self._xmlrpc_proxy.Component.update(paramdict)

    def product_get(self, paramdict):
        return self._xmlrpc_proxy.Product.get(paramdict)
    def product_get_accessible(self):
        return self._xmlrpc_proxy.Product.get_accessible_products()
    def product_get_enterable(self):
        return self._xmlrpc_proxy.Product.get_enterable_products()
    def product_get_selectable(self):
        return self._xmlrpc_proxy.Product.get_selectable_products()

    def user_create(self, paramdict):
        return self._xmlrpc_proxy.User.create(paramdict)
    def user_get(self, paramdict):
        return self._xmlrpc_proxy.User.get(paramdict)
    def user_login(self, paramdict):
        return self._xmlrpc_proxy.User.login(paramdict)
    def user_logout(self):
        return self._xmlrpc_proxy.User.logout()
    def user_update(self, paramdict):
        return self._xmlrpc_proxy.User.update(paramdict)