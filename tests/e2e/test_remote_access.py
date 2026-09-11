import pytest
import requests
from playwright.sync_api import APIRequestContext

from tests.test_config import TestConfig, TestUtils
from web.tunnel import REMOTE_SESSION_MAX_AGE

PRIVATE_EVENT_ID = 'test-event-remote-access-private'

WEB_URL = f'http://{TestConfig.TEST_HOST}:{TestConfig.TEST_PORT}'
TUNNEL_URL = f'http://{TestConfig.TEST_HOST}:{TestConfig.TEST_TUNNEL_PORT}'


@pytest.fixture(scope='module', autouse=True)
def private_event(api_request_context: APIRequestContext):
    TestUtils.create_event(
        PRIVATE_EVENT_ID,
        api_request_context,
        {'public': False},
    )

    yield

    TestUtils.delete_event(PRIVATE_EVENT_ID, api_request_context)


@pytest.mark.e2e
class TestRemoteAccess:
    def test_the_web_listener_grants_the_machine_itself_the_administrator_account(
        self,
    ):
        response = requests.get(
            f'{WEB_URL}/event/{PRIVATE_EVENT_ID}',
            timeout=10,
            allow_redirects=False,
        )

        assert response.status_code == 302
        assert PRIVATE_EVENT_ID in response.headers['location']

    def test_the_tunnel_listener_does_not_grant_the_administrator_account(self):
        """The tunnel client runs on this machine, so its requests reach the
        server from the loopback address just as the local browser's do.  They
        must still be treated as coming from the internet."""
        response = requests.get(
            f'{TUNNEL_URL}/event/{PRIVATE_EVENT_ID}',
            timeout=10,
            allow_redirects=False,
        )

        assert response.status_code == 302
        assert PRIVATE_EVENT_ID not in response.headers['location']

    def test_a_session_opened_from_the_internet_is_secure_and_short_lived(self):
        response = requests.get(f'{TUNNEL_URL}/', timeout=10, allow_redirects=False)

        set_cookie = response.headers['set-cookie']

        assert 'Secure' in set_cookie
        assert f'Max-Age={REMOTE_SESSION_MAX_AGE}' in set_cookie

    def test_a_session_opened_on_the_local_network_keeps_its_own_terms(self):
        response = requests.get(f'{WEB_URL}/', timeout=10, allow_redirects=False)

        set_cookie = response.headers['set-cookie']

        assert 'Secure' not in set_cookie
        assert f'Max-Age={REMOTE_SESSION_MAX_AGE}' not in set_cookie


@pytest.mark.e2e
class TestInstanceIdentity:
    def test_a_hostname_no_event_is_live_on_says_so(self):
        response = requests.get(
            f'{TUNNEL_URL}/.well-known/sharly-chess-instance',
            timeout=10,
            headers={'Host': 'nobody.live.example.com'},
            allow_redirects=False,
        )

        assert response.status_code == 404


@pytest.mark.e2e
class TestRemoteAccessSignIn:
    """The sign-in is reached by ordinary navigation from the application
    window, so it has to answer with something a browser will follow."""

    def test_signing_in_sends_the_browser_somewhere(self):
        response = requests.get(
            f'{WEB_URL}/remote-access/sign-in',
            timeout=10,
            allow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers['location']

    def test_signing_out_sends_the_browser_somewhere(self):
        response = requests.get(
            f'{WEB_URL}/remote-access/sign-out',
            timeout=10,
            allow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers['location']

    def test_a_code_nobody_is_waiting_for_is_refused_rather_than_honoured(self):
        response = requests.get(
            f'{WEB_URL}/remote-access/callback',
            params={'code': 'invented', 'state': 'nobody-is-waiting'},
            timeout=10,
            allow_redirects=False,
        )

        assert response.status_code == 302


@pytest.mark.e2e
class TestCrawlers:
    """What is said to whoever is reading the server rather than using it."""

    def test_crawlers_are_asked_to_leave_the_event_alone(self):
        response = requests.get(f'{WEB_URL}/robots.txt', timeout=10)

        assert response.status_code == 200
        assert 'Disallow: /' in response.text

    def test_every_page_says_it_too(self):
        """A crawler arriving by a link elsewhere has not read the file."""
        response = requests.get(f'{WEB_URL}/robots.txt', timeout=10)

        assert 'noindex' in response.headers.get('X-Robots-Tag', '')


@pytest.mark.e2e
class TestProbes:
    """What a stranger guessing at filenames is answered with.

    Anything reachable from the internet is guessed at continuously. A refusal
    is the right answer; a server error is an invitation to keep going, and it
    fills the log of a laptop that is running a tournament.
    """

    @pytest.mark.parametrize(
        'path',
        ['/config.json', '/.env', '/app.css', '/settings.json', '/static/nothing.json'],
    )
    def test_a_guess_at_a_filename_is_refused_rather_than_failing(self, path):
        response = requests.get(f'{WEB_URL}{path}', timeout=10, allow_redirects=False)

        assert response.status_code < 500

    def test_a_method_the_server_does_not_answer_is_refused(self):
        response = requests.post(
            f'{WEB_URL}/graphql', timeout=10, allow_redirects=False
        )

        assert response.status_code < 500
