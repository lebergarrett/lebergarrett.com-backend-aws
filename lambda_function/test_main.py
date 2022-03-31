import unittest
from main import lambda_handler


class TestLambda(unittest.TestCase):
    def test_lambda_handler(self):
        self.assertEqual(lambda_handler("status","test")["statusCode"],200)

if __name__ == '__main__':
    unittest.main()