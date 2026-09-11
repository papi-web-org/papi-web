import re

import pytest
import requests
from playwright.sync_api import APIRequestContext

from tests.test_config import TestConfig, TestUtils
from web.login_throttle import ACCOUNT_FREE_ATTEMPTS

EVENT_ID = 'test-event-login-throttle'
FIRST_NAME = 'throttle'
LAST_NAME = 'TEST'
FULL_NAME = f'{FIRST_NAME} {LAST_NAME}'
PASSWORD = 'test-password'

FORM_HEADERS = {'Content-Type': 'application/x-www-form-urlencoded'}

#: The log-in form is only offered to a client that is not the machine itself,
#: so the attempts are made over the tunnel listener.
TUNNEL_URL = f'http://{TestConfig.TEST_HOST}:{TestConfig.TEST_TUNNEL_PORT}'
WEB_URL = f'http://{TestConfig.TEST_HOST}:{TestConfig.TEST_PORT}'


@pytest.fixture(scope='module', autouse=True)
def account(api_request_context: APIRequestContext):
    TestUtils.create_event(EVENT_ID, api_request_context)
    response = api_request_context.post(
        f'/account-create/{EVENT_ID}',
        headers=FORM_HEADERS,
        data=TestUtils.prepare_form_data(
            {
                'first_name': FIRST_NAME,
                'last_name': LAST_NAME,
                'password': PASSWORD,
                'active': True,
            }
        ),
    )
    TestUtils.check_api_response(response)

    yield

    TestUtils.delete_event(EVENT_ID, api_request_context)


def account_id() -> str:
    """The id the log-in form offers for the account, read from the form itself."""
    response = requests.get(f'{TUNNEL_URL}/profile-modal/{EVENT_ID}', timeout=10)
    assert response.status_code == 200
    match = re.search(
        rf'<option value="(\d+)"[^>]*>\s*{FULL_NAME}', response.text, re.MULTILINE
    )
    assert match is not None, f'[{FULL_NAME}] is not offered by the log-in form'
    return match.group(1)


def attempt_login(password: str) -> str:
    response = requests.post(
        f'{TUNNEL_URL}/profile-login/{EVENT_ID}',
        headers=FORM_HEADERS,
        data={'account_id': account_id(), 'password': password},
        timeout=10,
    )
    return response.text


@pytest.mark.e2e
class TestLoginThrottle:
    def test_a_run_of_wrong_passwords_stops_being_answered(self):
        for __ in range(ACCOUNT_FREE_ATTEMPTS + 1):
            assert 'Invalid password.' in attempt_login('wrong-password')

        assert 'Too many failed attempts' in attempt_login('wrong-password')

    def test_the_right_password_is_still_refused_while_locked_out(self):
        assert 'Too many failed attempts' in attempt_login(PASSWORD)
