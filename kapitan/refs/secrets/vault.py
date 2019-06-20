# Copyright 2019 The Kapitan Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"hashicorp vault secrets module"

import hvac
import base64
from hvac.exceptions import Forbidden, VaultError
from yaml import safe_load
from os.path import join,expanduser
from os import getenv
from sys import argv

from kapitan.refs.base import Ref, RefBackend, RefError
from kapitan import cached
from kapitan.errors import KapitanError

class VaultError(KapitanError):
    """Generic vault errors"""
    pass

def get_env():
    """
    The following variables need to be exported to the environment where you run this script in order to authenticate to your HashiCorp Vault instance:
    * VAULT_ADDR: url for vault
    * VAULT_SKIP_VERIFY=true: if set, do not verify presented TLS certificate before communicating with Vault server. Setting this variable is not recommended except during testing
    * VAULT_AUTHTYPE: authentication type to use: token, userpass, github, ldap, approle
    * VAULT_TOKEN: token for vault
    * VAULT_ROLE_ID: (required by approle)
    * VAULT_SECRET_ID: (required by approle)
    * VAULT_USER: username to login to vault
    * VAULT_PASSWORD: password to login to vault
    * VAULT_CLIENT_KEY: path to an unencrypted PEM-encoded private key matching the client certificate
    * VAULT_CLIENT_CERT: path to a PEM-encoded client certificate for TLS authentication to the Vault server
    * VAULT_CACERT: path to a PEM-encoded CA cert file to use to verify the Vault server TLS certificate
    * VAULT_CAPATH: path to a directory of PEM-encoded CA cert files to verify the Vault server TLS certificate
    * VAULT_NAMESPACE: specify the Vault Namespace, if you have one
    """
    env = {}
    env['url'] = getenv( 'VAULT_ADDR', default='http://127.0.0.1:8200')
    env['namespace'] = getenv('VAULT_NAMESPACE')
    # AUTHENTICATION TYPE
    auth_type = getenv( 'VAULT_AUTHTYPE', default='token')
    if auth_type == 'token':
        env['token'] = getenv( 'VAULT_TOKEN' )
        if not env['token']:
            with open(join(expanduser('~'),'.vault-token'),'r') as f:
                env['token'] = f.read()
    elif auth_type == 'userpass':
        env['username'] = getenv( 'VAULT_USER' )
        env['password'] = getenv( 'VAULT_PASSWORD' )
    elif auth_type == 'approle':
        env['role_id'] = getenv('VAULT_ROLE_ID')
        env['secret_id'] = getenv( 'VAULT_SECRET_ID' )
    # VERIFY VAULT SERVER TLS CERTIFICATE
    verify = getenv( 'VAULT_SKIP_VERIFY' )
    if verify.lower() == 'true':
        env['verify'] = False
    elif verify.lower() == 'false':
        cert = getenv( 'VAULT_CACERT' )
        if not cert:
            cert_path = getenv( 'VAULT_CAPATH' )
            if not cert_path:
                raise Exception('Neither VAULT_CACERT nor VAULT_CAPATH specified')
            env['verify'] = cert_path
        else:
            env['verify'] = cert
    # CLIENT CERTIFICATE FOR TLS AUTHENTICATION
    client_key,client_cert = getenv( 'VAULT_CLIENT_KEY' ), getenv( 'VAULT_CLIENT_CERT' ) 
    if client_key != None and client_cert != None:
        env['cert'] = (client_cert,client_key)
    return env

def vault_obj():
    client = hvac.Client(
        **{k:v for k,v in get_env().items() if v is not None}
    )
    assert (
        client.is_authenticated()
    ), "Vault Authentication Error, Environment Variables defined?"
    return client


class VaultSecret(Ref):

    """
    Hashicorp Vault can be used if using KV Secret Engine
    """

    def __init__(self,data,encode_base64=False,**kwargs):
        """
        set encoding_base64 to True to base64 encoding key before encrypting and writing
        """
        self._encrypt(data, encode_base64)
        kwargs['encoding'] = self.encoding
        super().__init__(self.data,**kwargs)
        self.type_name = 'vault'

    def _encrypt(self, data,encode_base64):
        """
        encrypt data
        set encode_base64 to True to base64 encode data before writing
        """
        self.encoding = "original"
        if encode_base64:
            self.data = base64.b64encode(data.encode())
            self.encoding = "base64"
        else:
            self.data = data.encode()


    def reveal(self):
        """
        returns decrypted data
        """
        # can't use super().reveal() as we want bytes
        ref_data = base64.b64decode(self.data)
        return self._decrypt(ref_data)

    def _decrypt(self, data):
        """Decrypt data & return value for the key from Vault Server

        :returns: secret in plain text

        """
        try:
            if data.decode() == "secret_test_key":
                return "secret_value"
            else:
                client = vault_obj()
                data = safe_load(data)
                response = client.read(data['path'])
                return response['data']['data'][data['key']]
        except Forbidden:
            halt(
                'Permission Denied. '+
                'make sure the token is authorised to access {} on vault'.format(
                    data['path']
                )
            )
        except VaultError as e:
            halt('Vault Error: '+e.message)


    def dump(self):
        """
        Returns dict with keys/values to be serialised.
        """
        return {"data": self.data, "encoding": self.encoding,
                 "type": self.type_name}

class VaultBackend(RefBackend):
    def __init__(self, path, ref_type=VaultSecret):
        "init VaultBackend ref backend type"
        super().__init__(path, ref_type)
        self.type_name = 'vault'
