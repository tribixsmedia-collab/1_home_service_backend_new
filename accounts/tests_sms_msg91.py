"""
The MSG91 request has to be right before anyone can test it for real.

Nothing here calls MSG91. The point is the shape of the request and the
reading of the reply, both verified against docs.msg91.com/sms/send-sms --
because under DLT the ways this fails are all quiet. A bare ten-digit number
is accepted and never delivered. A wrong variable name returns HTTP 200. Free
text is refused outright. None of it raises on its own.
"""

from unittest import mock

from django.test import SimpleTestCase, override_settings

from accounts import sms

OK = {'type': 'success', 'message': '5e1e99cad6fc054d8e769a5b'}


def fake_response(json_body=OK, status=200):
    resp = mock.Mock()
    resp.status_code = status
    resp.content = b'{}'
    resp.json.return_value = json_body
    resp.raise_for_status.return_value = None
    resp.text = str(json_body)
    return resp


@override_settings(
    SMS_BACKEND='msg91',
    MSG91_AUTH_KEY='test-authkey',
    MSG91_TEMPLATE_ID='650a1b2c3d4e5f6a7b8c9d0e',
    MSG91_OTP_VARIABLE='VAR1',
)
class Msg91RequestShapeTests(SimpleTestCase):

    def send(self, phone='9876543210', code='123456', response=None):
        with mock.patch('requests.post', return_value=response or fake_response()) as post:
            sms.send_otp_sms(phone, code)
        return post.call_args

    def test_posts_to_the_control_host_not_api(self):
        """api.msg91.com was the old host; the Flow API lives on control."""
        args, _ = self.send()
        self.assertEqual(args[0], 'https://control.msg91.com/api/v5/flow')

    def test_sends_the_template_id_and_no_free_text(self):
        """
        DLT forbids choosing the wording here. A `message` key would mean the
        old implementation had crept back.
        """
        _, kwargs = self.send()
        body = kwargs['json']
        self.assertEqual(body['template_id'], '650a1b2c3d4e5f6a7b8c9d0e')
        self.assertNotIn('message', body)
        self.assertNotIn('route', body)

    def test_adds_the_country_code_to_a_ten_digit_number(self):
        _, kwargs = self.send(phone='9876543210')
        self.assertEqual(kwargs['json']['recipients'][0]['mobiles'], '919876543210')

    def test_leaves_a_number_that_already_has_the_country_code(self):
        _, kwargs = self.send(phone='919876543210')
        self.assertEqual(kwargs['json']['recipients'][0]['mobiles'], '919876543210')

    def test_strips_a_leading_plus_and_spaces(self):
        _, kwargs = self.send(phone='+91 98765 43210')
        self.assertEqual(kwargs['json']['recipients'][0]['mobiles'], '919876543210')

    def test_the_code_goes_in_the_named_template_variable(self):
        _, kwargs = self.send(code='445566')
        self.assertEqual(kwargs['json']['recipients'][0]['VAR1'], '445566')

    @override_settings(MSG91_OTP_VARIABLE='otp')
    def test_the_variable_name_follows_the_template(self):
        """A template written with a named blank wants that name, not VAR1."""
        _, kwargs = self.send(code='778899')
        self.assertEqual(kwargs['json']['recipients'][0]['otp'], '778899')

    def test_asks_for_the_real_outcome_not_a_queue_receipt(self):
        _, kwargs = self.send()
        self.assertEqual(kwargs['json']['realTimeResponse'], '1')

    def test_sends_the_authkey_header(self):
        _, kwargs = self.send()
        self.assertEqual(kwargs['headers']['authkey'], 'test-authkey')


@override_settings(
    SMS_BACKEND='msg91',
    MSG91_AUTH_KEY='test-authkey',
    MSG91_TEMPLATE_ID='650a1b2c3d4e5f6a7b8c9d0e',
    MSG91_OTP_VARIABLE='VAR1',
)
class Msg91FailureTests(SimpleTestCase):
    """A 200 is not a delivery, and the code must not pretend otherwise."""

    def test_an_error_body_with_http_200_raises(self):
        refusal = fake_response({'type': 'error', 'message': 'template not approved'})
        with mock.patch('requests.post', return_value=refusal):
            with self.assertRaises(RuntimeError) as caught:
                sms.send_otp_sms('9876543210', '123456')
        self.assertIn('template not approved', str(caught.exception))

    def test_a_non_json_reply_raises_rather_than_passing_silently(self):
        html = fake_response()
        html.json.side_effect = ValueError('not json')
        html.text = '<html>gateway error</html>'
        with mock.patch('requests.post', return_value=html):
            with self.assertRaises(RuntimeError):
                sms.send_otp_sms('9876543210', '123456')

    @override_settings(MSG91_TEMPLATE_ID='')
    def test_a_missing_template_id_is_refused_before_the_call(self):
        """
        Sending without one would be a free-text message, which DLT rejects.
        Better to say so than to let MSG91 answer 200 and deliver nothing.
        """
        with mock.patch('requests.post') as post:
            with self.assertRaises(ValueError) as caught:
                sms.send_otp_sms('9876543210', '123456')
        post.assert_not_called()
        self.assertIn('MSG91_TEMPLATE_ID', str(caught.exception))


class ConsoleBackendTests(SimpleTestCase):
    @override_settings(SMS_BACKEND='console')
    def test_console_still_sends_nothing(self):
        """The development default must never reach the network."""
        with mock.patch('requests.post') as post:
            sms.send_otp_sms('9876543210', '123456')
        post.assert_not_called()
