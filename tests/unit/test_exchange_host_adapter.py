import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import requests
from requests.auth import HTTPBasicAuth
from requests_ntlm import HttpNtlmAuth

from routers.communications import EXCHANGE_EWS_HOST, _ExchangeHostAdapter, _exchange_ews_post


class ExchangeHostAdapterTests(unittest.TestCase):
    def test_ip_connection_keeps_exchange_certificate_name(self):
        request = requests.Request("GET", "https://194.186.48.76/EWS/Exchange.asmx").prepare()
        adapter = _ExchangeHostAdapter()

        host_params, pool_kwargs = adapter.build_connection_pool_key_attributes(request, True)

        self.assertEqual(host_params["host"], "194.186.48.76")
        self.assertEqual(pool_kwargs["server_hostname"], EXCHANGE_EWS_HOST)
        self.assertEqual(pool_kwargs["assert_hostname"], EXCHANGE_EWS_HOST)

    def test_ews_uses_basic_then_ntlm_if_basic_is_rejected(self):
        session = SimpleNamespace(ews_url="https://mail.korda.spb.ru/EWS/Exchange.asmx", post=Mock())
        session.post.side_effect = [SimpleNamespace(status_code=401), SimpleNamespace(status_code=200)]

        response = _exchange_ews_post(session, b"<test/>", "user", "secret", (5, 10))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(session.post.call_count, 2)
        self.assertIsInstance(session.post.call_args_list[0].kwargs["auth"], HTTPBasicAuth)
        self.assertIsInstance(session.post.call_args_list[1].kwargs["auth"], HttpNtlmAuth)


if __name__ == "__main__":
    unittest.main()
