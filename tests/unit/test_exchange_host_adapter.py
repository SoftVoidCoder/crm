import unittest

import requests

from routers.communications import EXCHANGE_EWS_HOST, _ExchangeHostAdapter


class ExchangeHostAdapterTests(unittest.TestCase):
    def test_ip_connection_keeps_exchange_certificate_name(self):
        request = requests.Request("GET", "https://194.186.48.76/EWS/Exchange.asmx").prepare()
        adapter = _ExchangeHostAdapter()

        host_params, pool_kwargs = adapter.build_connection_pool_key_attributes(request, True)

        self.assertEqual(host_params["host"], "194.186.48.76")
        self.assertEqual(pool_kwargs["server_hostname"], EXCHANGE_EWS_HOST)
        self.assertEqual(pool_kwargs["assert_hostname"], EXCHANGE_EWS_HOST)


if __name__ == "__main__":
    unittest.main()
