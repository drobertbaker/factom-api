import random
import string
import time
try:
    from urllib.parse import urlparse, urljoin  # noqa
except ImportError:
    from urlparse import urlparse, urljoin  # noqa

from .exceptions import handle_error_response
from .session import FactomAPISession
from .utils import hex, unhex


NULL_BLOCK = '0000000000000000000000000000000000000000000000000000000000000000'  # noqa


class BaseAPI(object):

    def __init__(self, ec_address=None, fct_address=None, host=None,
                 version='v2', username=None, password=None, certfile=None):
        """
        Instantiate a new API client.

        Args:
            ec_address (str): A default entry credit address to use for
                transactions. Credits will be spent from this address with the
                exception of the `fct_to_ec()` shortcut.
            fa_address (str): A default factoid address to use for
                transactions. Factoids will be spent from this address.
            host (str): Hostname, including http(s)://, of the factomd or
                factom-walletd instance to query.
            version (str): API version to use. This should remain 'v2'.
            username (str): RPC username for protected APIs.
            password (str): RPC password for protected APIs.
            certfile (str): Path to certificate file to verify for TLS
                connections (mostly untested).
        """
        self.ec_address = ec_address
        self.fct_address = fct_address
        self.version = version

        if host:
            self.host = host

        self.session = FactomAPISession()

        if username and password:
            self.session.init_basic_auth(username, password)

        if certfile:
            self.session.init_tls(certfile)

    @property
    def url(self):
        return urljoin(self.host, self.version)

    def _xact_name(self):
        return 'TX_{}'.format(''.join(random.choices(
            string.ascii_uppercase + string.digits, k=6)))

    def _request(self, method, params=None, id=0):
        data = {
            'jsonrpc': '2.0',
            'id': id,
            'method': method,
        }
        if params:
            data['params'] = params

        resp = self.session.request('POST', self.url, json=data)

        if resp.status_code >= 400:
            handle_error_response(resp)

        return resp.json()['result']


class Factomd(BaseAPI):
    host = 'http://localhost:8088'

    def chain_head(self, chain_id):
        return self._request('chain-head', {
            'chainid': chain_id
        })

    def commit_chain(self, message):
        return self._request('commit-chain', {
            'message': message
        })

    def commit_entry(self, message):
        return self._request('commit-entry', {
            'message': message
        })

    def entry(self, hash):
        return self._request('entry', {
            'hash': hash
        })

    def entry_block(self, keymr):
        return self._request('entry-block', {
            'keymr': keymr
        })

    def entry_credit_balance(self, ec_address=None):
        return self._request('entry-credit-balance', {
            'address': ec_address or self.ec_address
        })

    def entry_credit_rate(self):
        return self._request('entry-credit-rate')

    def factoid_balance(self, fct_address=None):
        return self._request('factoid-balance', {
            'address': fct_address or self.fct_address
        })

    def factoid_submit(self, transaction):
        return self._request('factoid-submit', {
            'transaction': transaction
        })

    def reveal_chain(self, entry):
        return self._request('reveal-chain', {
            'entry': entry
        })

    def reveal_entry(self, entry):
        return self._request('reveal-entry', {
            'entry': entry
        })

    # Convenience methods

    def read_chain(self, chain_id):
        """
        Shortcut method to read an entire chain.

        Args:
            chain_id (str): Chain ID to read.

        Returns:
            list[dict]: A list of entry dictionaries in reverse
                chronologial order.
        """
        entries = []
        keymr = self.chain_head(chain_id)['chainhead']
        while keymr != NULL_BLOCK:
            block = self.entry_block(keymr)
            for hash in reversed(block['entrylist']):
                entry = self.entry(hash['entryhash'])
                entries.append({
                    'chainid': entry['chainid'],
                    'extids': unhex(entry['extids']),
                    'content': unhex(entry['content']),
                })
            keymr = block['header']['prevkeymr']
        return entries


class FactomWalletd(BaseAPI):
    host = 'http://localhost:8089'

    def add_ec_output(self, name, amount, ec_address=None):
        return self._request('add-ec-output', {
            'tx-name': name,
            'amount': amount,
            'address': ec_address or self.ec_address
        })

    def add_fee(self, name, fct_address=None):
        return self._request('add-fee', {
            'tx-name': name,
            'address': fct_address or self.fct_address
        })

    def add_input(self, name, amount, fct_address=None):
        return self._request('add-input', {
            'tx-name': name,
            'amount': amount,
            'address': fct_address or self.fct_address
        })

    def add_output(self, name, amount, fct_address):
        return self._request('add-output', {
            'tx-name': name,
            'amount': amount,
            'address': fct_address
        })

    def compose_transaction(self, name):
        return self._request('compose-transaction', {
            'tx-name': name
        })

    def new_transaction(self, name=None):
        return self._request('new-transaction', {
            'tx-name': name or self._xact_name()
        })

    def sign_transaction(self, name):
        return self._request('sign-transaction', {
            'tx-name': name
        })

    def sub_fee(self, name, fct_address):
        return self._request('sub-fee', {
            'tx-name': name,
            'address': fct_address
        })

    # Convenience methods

    def new_chain(self, factomd, ext_ids, content, ec_address=None):
        """
        Shortcut method to create a new chain and initial entry.

        Args:
            factomd (Factomd): The `Factomd` instance where the creation
                message will be submitted.
            ext_ids (list[str]): A list of external IDs, unencoded.
            content (str): Entry content, unencoded.
            ec_address (str): Entry credit address to pay with. If not
                provided `self.ec_address` will be used.

        Returns:
            dict: API result from the final `reveal_chain()` call.
        """
        calls = self._request('compose-chain', {
            'chain': {
                'firstentry': {
                    'extids': hex(ext_ids),
                    'content': hex(content)
                },
            },
            'ecpub': ec_address or self.ec_address
        })
        factomd.commit_chain(calls['commit']['params']['message'])
        time.sleep(2)
        return factomd.reveal_chain(calls['reveal']['params']['entry'])

    def new_entry(self, factomd, chain_id, ext_ids, content, ec_address=None):
        """
        Shortcut method to create a new entry.

        Args:
            factomd (Factomd): The `Factomd` instance where the creation
                message will be submitted.
            chain_id (str): Chain ID where entry will be appended.
            ext_ids (list[str]): A list of external IDs, unencoded.
            content (str): Entry content, unencoded.
            ec_address (str): Entry credit address to pay with. If not
                provided `self.ec_address` will be used.

        Returns:
            dict: API result from the final `reveal_chain()` call.
        """
        calls = self._request('compose-entry', {
            'entry': {
                'chainid': chain_id,
                'extids': hex(ext_ids),
                'content': hex(content)
            },
            'ecpub': ec_address or self.ec_address
        })
        factomd.commit_entry(calls['commit']['params']['message'])
        time.sleep(2)
        return factomd.reveal_entry(calls['reveal']['params']['entry'])

    def fct_to_ec(self, factomd, amount, fct_address=None, ec_address=None):
        """
        Shortcut method to create a factoid to entry credit transaction.

        factomd (Factomd): The `Factomd` instance where the signed
            transaction will be submitted.
        amount (int): Amount of fct to submit for conversion. You'll likely
            want to first query the exchange rate via
            `Factomd.entry_credit_rate()`.
        fct_address (str): Factoid address to pay with. If not provided
            `self.fct_address` will be used.
        ec_address (str): Entry credit address to receive credits. If not
            provided `self.ec_address` will be used.

        Returns:
            dict: API result from the final `factoid_submit()` call.
        """
        name = self._xact_name()
        self.new_transaction(name)
        self.add_input(name, amount, fct_address)
        self.add_ec_output(name, amount, ec_address)
        self.add_fee(name, fct_address)
        self.sign_transaction(name)
        call = self.compose_transaction(name)
        return factomd.factoid_submit(call['params']['transaction'])

    def fct_to_fct(self, factomd, amount, fct_to, fct_from=None):
        """
        Shortcut method to create a factoid to factoid.

        factomd (Factomd): The `Factomd` instance where the signed
            transaction will be submitted.
        amount (int): Amount of fct to submit for conversion. You'll likely
            want to first query the exchange rate via
            `Factomd.entry_credit_rate()`.
        fct_to (str): Output factoid address.
        fct_from (str): Input factoid address. If not provided
            `self.fct_address` will be used.

        Returns:
            dict: API result from the final `factoid_submit()` call.
        """
        name = self._xact_name()
        self.new_transaction(name)
        self.add_input(name, amount, fct_from)
        self.add_output(name, amount, fct_to)
        self.add_fee(name, fct_from)
        self.sign_transaction(name)
        call = self.compose_transaction(name)
        return factomd.factoid_submit(call['params']['transaction'])
