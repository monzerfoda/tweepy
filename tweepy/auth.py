# Tweepy
# Copyright 2009-2022 Joshua Roesslein
# See LICENSE for details.

from base64 import urlsafe_b64encode
from hashlib import sha256
import logging
from urllib.parse import parse_qs
import secrets

import requests
from requests.auth import AuthBase, HTTPBasicAuth
from requests_oauthlib import OAuth1, OAuth1Session, OAuth2Session

from tweepy.errors import TweepyException

WARNING_MESSAGE = """Warning! Due to a Twitter API bug, signin_with_twitter
and access_type don't always play nice together. Details
https://dev.twitter.com/discussions/21281"""

log = logging.getLogger(__name__)


class AuthHandler:

    def apply_auth(self, url, method, headers, parameters):
        """Apply authentication headers to request"""
        raise NotImplementedError


class OAuthHandler(AuthHandler):
    """OAuth authentication handler"""
    OAUTH_HOST = 'api.twitter.com'
    OAUTH_ROOT = '/oauth/'

    def __init__(self, consumer_key, consumer_secret, callback=None):
        if not isinstance(consumer_key, (str, bytes)):
            raise TypeError("Consumer key must be string or bytes, not "
                            + type(consumer_key).__name__)
        if not isinstance(consumer_secret, (str, bytes)):
            raise TypeError("Consumer secret must be string or bytes, not "
                            + type(consumer_secret).__name__)

        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.access_token = None
        self.access_token_secret = None
        self.callback = callback
        self.username = None
        self.request_token = {}
        self.oauth = OAuth1Session(consumer_key,
                                   client_secret=consumer_secret,
                                   callback_uri=self.callback)

    def _get_oauth_url(self, endpoint):
        return 'https://' + self.OAUTH_HOST + self.OAUTH_ROOT + endpoint

    def apply_auth(self):
        return OAuth1(self.consumer_key,
                      client_secret=self.consumer_secret,
                      resource_owner_key=self.access_token,
                      resource_owner_secret=self.access_token_secret,
                      decoding=None)

    def _get_request_token(self, access_type=None):
        try:
            url = self._get_oauth_url('request_token')
            if access_type:
                url += f'?x_auth_access_type={access_type}'
            return self.oauth.fetch_request_token(url)
        except Exception as e:
            raise TweepyException(e)

    def set_access_token(self, key, secret):
        self.access_token = key
        self.access_token_secret = secret

    def get_authorization_url(self,
                              signin_with_twitter=False,
                              access_type=None):
        """Get the authorization URL to redirect the user"""
        try:
            if signin_with_twitter:
                url = self._get_oauth_url('authenticate')
                if access_type:
                    log.warning(WARNING_MESSAGE)
            else:
                url = self._get_oauth_url('authorize')
            self.request_token = self._get_request_token(access_type=access_type)
            return self.oauth.authorization_url(url)
        except Exception as e:
            raise TweepyException(e)

    def get_access_token(self, verifier=None):
        """
        After user has authorized the request token, get access token
        with user supplied verifier.
        """
        try:
            url = self._get_oauth_url('access_token')
            self.oauth = OAuth1Session(self.consumer_key,
                                       client_secret=self.consumer_secret,
                                       resource_owner_key=self.request_token['oauth_token'],
                                       resource_owner_secret=self.request_token['oauth_token_secret'],
                                       verifier=verifier, callback_uri=self.callback)
            resp = self.oauth.fetch_access_token(url)
            self.access_token = resp['oauth_token']
            self.access_token_secret = resp['oauth_token_secret']
            return self.access_token, self.access_token_secret
        except Exception as e:
            raise TweepyException(e)

    def get_xauth_access_token(self, username, password):
        """
        Get an access token from an username and password combination.
        In order to get this working you need to create an app at
        http://twitter.com/apps, after that send a mail to api@twitter.com
        and request activation of xAuth for it.
        """
        try:
            url = self._get_oauth_url('access_token')
            oauth = OAuth1(self.consumer_key,
                           client_secret=self.consumer_secret)
            r = requests.post(url=url,
                              auth=oauth,
                              headers={'x_auth_mode': 'client_auth',
                                       'x_auth_username': username,
                                       'x_auth_password': password})

            credentials = parse_qs(r.content)
            return credentials.get('oauth_token')[0], credentials.get('oauth_token_secret')[0]
        except Exception as e:
            raise TweepyException(e)


class OAuth2Handler(OAuth2Session):

    def __init__(self, *, client_id, redirect_uri, scope, client_secret=None):
        super().__init__(client_id, redirect_uri=redirect_uri, scope=scope)
        if client_secret is not None:
            self.auth = HTTPBasicAuth(client_id, client_secret)
        else:
            self.auth = None

    def get_authorization_url(self):
        self.code_verifier = secrets.token_urlsafe(128)[:128]
        code_challenge = urlsafe_b64encode(
            sha256(self.code_verifier.encode("ASCII")).digest()
        ).rstrip(b'=')
        authorization_url, state = self.authorization_url(
            "https://twitter.com/i/oauth2/authorize",
            code_challenge=code_challenge, code_challenge_method="s256"
        )
        return authorization_url

    def fetch_token(self, authorization_response):
        return super().fetch_token(
            "https://api.twitter.com/2/oauth2/token",
            authorization_response=authorization_response,
            auth=self.auth,
            include_client_id=True,
            code_verifier=self.code_verifier
        )


class OAuth2Bearer(AuthBase):

    def __init__(self, bearer_token):
        self.bearer_token = bearer_token

    def __call__(self, request):
        request.headers['Authorization'] = 'Bearer ' + self.bearer_token
        return request


class AppAuthHandler(AuthHandler):
    """Application-only authentication handler"""

    OAUTH_HOST = 'api.twitter.com'
    OAUTH_ROOT = '/oauth2/'

    def __init__(self, consumer_key, consumer_secret):
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self._bearer_token = ''

        resp = requests.post(self._get_oauth_url('token'),
                             auth=(self.consumer_key,
                                   self.consumer_secret),
                             data={'grant_type': 'client_credentials'})
        data = resp.json()
        if data.get('token_type') != 'bearer':
            raise TweepyException('Expected token_type to equal "bearer", '
                                  f'but got {data.get("token_type")} instead')

        self._bearer_token = data['access_token']

    def _get_oauth_url(self, endpoint):
        return 'https://' + self.OAUTH_HOST + self.OAUTH_ROOT + endpoint

    def apply_auth(self):
        return OAuth2Bearer(self._bearer_token)
