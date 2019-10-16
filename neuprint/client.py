# -*- coding: utf-8 -*-
import copy
import json
import os
import sys

import pandas as pd
import requests


class Client:
    """ Holds your NeuPrint credentials and does the data fetching.

    Parameters
    ----------
    server :        str
                    URL of server.
    token :         str, optional
                    NeuPrint token. Either pass explitily as an argument or set
                    as NEUPRINT_APPLICATION_CREDENTIALS environment variable.
                    Your token can be retrieved by clicking on your account in
                    the NeuPrint web interface.
    set_global :    bool, optional
                    If True (default), will make this client global so that
                    you don't have to explicitly pass it to each function.
    """

    def __init__(self, server, token=None, set_global=True):
        if token is None:
            token = os.environ.get('NEUPRINT_APPLICATION_CREDENTIALS')

        if token is None:
            raise RuntimeError("No token provided. Please provide one or set NEUPRINT_APPLICATION_CREDENTIALS")

        if ':' in token:
            try:
                token = json.loads(token)['token']
            except Exception:
                raise RuntimeError("Did not understand token. Please provide the entire JSON document or (only) the complete token string")

        token = token.replace('"', '')

        if '://' not in server:
            server = 'https://' + server
        elif server.startswith('http://'):
            raise RuntimeError("Server must be https, not http")
        elif not server.startswith('https://'):
            raise RuntimeError("Unknown protocol: {}".format(server.split('://')[0]))

        self.server = server
        self.session = requests.Session()
        self.session.headers.update({"Authorization": "Bearer " + token,
                                     "Content-type": "application/json"})
        self.verbose = False

        if set_global:
            self.make_global()

    def make_global(self):
        """Sets this variable as global by attaching it as sys.module"""
        sys.modules['NEUPRINT_CLIENT'] = self

    def _fetch(self, url, json=None):
        if self.verbose:
            print('url:', url)
            print('cypher:', json.get('cypher'))

        try:
            r = self.session.get(url, json=json)
            r.raise_for_status()
            return r
        except requests.RequestException as ex:
            # If the error response had content (and it's not super-long),
            # show that in the traceback, too.  neuprint might provide a useful
            # error message in the response body.
            if (ex.response is not None or ex.request is not None):
                msg = ""
                if (ex.request is not None):
                    msg += "Error accessing {} {}\n".format(ex.request.method, ex.request.url)
                    cypher = json.get('cypher')
                    if cypher:
                        msg += "Cypher was:\n{}\n".format(cypher)
                
                if (ex.response is not None and ex.response.content and len(ex.response.content) <= 200):
                    msg += str(ex.args[0]) + "\n" + ex.response.content.decode('utf-8') + "\n"

                new_ex = copy.copy(ex)
                new_ex.args = (msg, *ex.args[1:])
                raise new_ex from ex
            else:
                raise

    def _fetch_raw(self, url, json=None):
        return self._fetch(url, json=json).content

    def _fetch_json(self, url, json=None):
        return self._fetch(url, json=json).json()

    def fetch_help(self):
        return self._fetch_raw("{}/api/help".format(self.server))

    def fetch_version(self):
        return self._fetch_json("{}/api/version".format(self.server))

    def fetch_available(self):
        return self._fetch_json("{}/api/available".format(self.server))

    def fetch_database(self):
        """ Fetch available datasets.
        """
        return self._fetch_json("{}/api/dbmeta/database".format(self.server))

    def fetch_datasets(self):
        """ Fetch available datasets.
        """
        return self._fetch_json("{}/api/dbmeta/datasets".format(self.server))

    def fetch_custom(self, cypher, format='pandas'):
        """ Fetch custom cypher.
        """
        if set("‘’“”").intersection(cypher):
            msg = ("Your cypher query contains 'smart quotes' (e.g. ‘foo’ or “foo”),"
                   " which are not valid characters in cypher."
                   " Please replace them with ordinary quotes (e.g. 'foo' or \"foo\").\n"
                   "Your query was:\n"
                   + cypher)
            raise RuntimeError(msg)
        
        assert format in ('json', 'pandas')
        result = self._fetch_json("{}/api/custom/custom".format(self.server),
                                  json={"cypher": cypher})
        if format == 'json':
            return result

        df = pd.DataFrame(result['data'], columns=result['columns'])
        return df
