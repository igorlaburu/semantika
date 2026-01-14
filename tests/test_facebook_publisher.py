"""Unit tests for facebook_publisher module.

Tests the Facebook Graph API publisher for company pages.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import aiohttp
from publishers.facebook_publisher import FacebookPublisher
from publishers.base_publisher import PublicationResult


@pytest.fixture
def facebook_credentials():
    """Sample Facebook credentials for testing."""
    return {
        'user_access_token': 'user_token_123',
        'page_access_token': 'page_token_456',
        'page_id': '123456789',
        'page_name': 'Test Page',
        'user_id': '987654321',
        'user_name': 'Test User',
        'available_pages': [
            {
                'id': '123456789',
                'name': 'Test Page',
                'access_token': 'page_token_456',
                'category': 'Business',
                'link': 'https://facebook.com/testpage'
            }
        ]
    }


@pytest.fixture
def facebook_publisher(facebook_credentials):
    """Create a FacebookPublisher instance for testing."""
    return FacebookPublisher(
        credentials=facebook_credentials,
        base_url='https://facebook.com/testpage'
    )


class TestFacebookPublisher:
    """Tests for FacebookPublisher class."""

    def test_get_platform_type(self, facebook_publisher):
        """Test platform type returns 'facebook'."""
        assert facebook_publisher.get_platform_type() == "facebook"

    def test_get_page_access_token(self, facebook_publisher):
        """Test page access token retrieval."""
        token = facebook_publisher._get_page_access_token()
        assert token == 'page_token_456'

    def test_get_page_access_token_missing(self):
        """Test error when page_access_token is missing."""
        publisher = FacebookPublisher(
            credentials={'user_access_token': 'test'},
            base_url='https://facebook.com/test'
        )
        with pytest.raises(ValueError, match="requires 'page_access_token'"):
            publisher._get_page_access_token()

    def test_format_hashtags(self, facebook_publisher):
        """Test hashtag formatting."""
        tags = ['Política', 'Economía', 'test tag']
        result = facebook_publisher._format_hashtags(tags)
        assert '#Política' in result
        assert '#Economía' in result
        assert '#testtag' in result

    def test_format_hashtags_limit(self, facebook_publisher):
        """Test hashtag limit (max 5)."""
        tags = ['one', 'two', 'three', 'four', 'five', 'six', 'seven']
        result = facebook_publisher._format_hashtags(tags)
        assert result.count('#') == 5

    def test_format_hashtags_empty(self, facebook_publisher):
        """Test empty tags handling."""
        assert facebook_publisher._format_hashtags([]) == ""
        assert facebook_publisher._format_hashtags(None) == ""

    def test_sanitize_content(self, facebook_publisher):
        """Test HTML content sanitization."""
        html_content = "<p>Hello <strong>World</strong></p>"
        result = facebook_publisher.sanitize_content(html_content)
        assert result == "Hello World"


@pytest.mark.asyncio
class TestFacebookPublisherAsync:
    """Async tests for FacebookPublisher."""

    async def test_test_connection_success(self, facebook_publisher):
        """Test successful connection check."""
        mock_response = {
            'name': 'Test Page',
            'id': '123456789',
            'link': 'https://facebook.com/testpage'
        }

        with patch('aiohttp.ClientSession') as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)

            mock_session_instance = MagicMock()
            mock_session_instance.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_resp)))
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await facebook_publisher.test_connection()

            assert result['success'] is True
            assert 'Test Page' in result['message']

    async def test_test_connection_failure(self, facebook_publisher):
        """Test connection check failure."""
        mock_error = {
            'error': {
                'message': 'Invalid OAuth access token',
                'type': 'OAuthException',
                'code': 190
            }
        }

        with patch('aiohttp.ClientSession') as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 401
            mock_resp.json = AsyncMock(return_value=mock_error)

            mock_session_instance = MagicMock()
            mock_session_instance.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_resp)))
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await facebook_publisher.test_connection()

            assert result['success'] is False
            assert 'Invalid OAuth access token' in result['message']

    async def test_publish_article_success(self, facebook_publisher):
        """Test successful article publication."""
        mock_response = {
            'id': '123456789_987654321'
        }

        with patch.object(facebook_publisher, '_post_to_page', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {
                'success': True,
                'post_id': '123456789_987654321'
            }

            result = await facebook_publisher.publish_article(
                title="Test Article",
                content="This is a test article content.",
                excerpt="Test excerpt",
                tags=["test", "article"]
            )

            assert result.success is True
            assert result.external_id == '123456789_987654321'
            assert result.metadata['platform'] == 'facebook'

    async def test_publish_article_no_page_id(self):
        """Test publishing fails without page_id."""
        publisher = FacebookPublisher(
            credentials={'page_access_token': 'test'},
            base_url='https://facebook.com/test'
        )

        result = await publisher.publish_article(
            title="Test",
            content="Content"
        )

        assert result.success is False
        assert 'No page_id configured' in result.error

    async def test_publish_article_preformatted(self, facebook_publisher):
        """Test publishing preformatted content."""
        preformatted = "📰 Test Title\n\nhttp://example.com\n\n#test"

        with patch.object(facebook_publisher, '_post_to_page', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {
                'success': True,
                'post_id': '123456789_111111111'
            }

            result = await facebook_publisher.publish_article(
                title="Ignored Title",
                content=preformatted
            )

            assert result.success is True
            # Check that the preformatted content was passed directly
            call_args = mock_post.call_args
            assert "📰 Test Title" in call_args[0][0]


class TestFacebookOAuth:
    """Tests for Facebook OAuth flow methods."""

    def test_get_authorization_url(self):
        """Test OAuth authorization URL generation."""
        url = FacebookPublisher.get_authorization_url(
            app_id='test_app_id',
            redirect_uri='https://example.com/callback',
            state='test_state_123'
        )

        assert 'https://www.facebook.com/' in url
        assert 'client_id=test_app_id' in url
        assert 'redirect_uri=' in url
        assert 'state=test_state_123' in url
        assert 'pages_manage_posts' in url
        assert 'pages_show_list' in url

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_success(self):
        """Test successful code exchange for token."""
        mock_response = {
            'access_token': 'new_access_token',
            'token_type': 'bearer',
            'expires_in': 5184000
        }

        with patch('aiohttp.ClientSession') as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)

            mock_session_instance = MagicMock()
            mock_session_instance.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_resp)))
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await FacebookPublisher.exchange_code_for_token(
                app_id='test_app',
                app_secret='test_secret',
                code='auth_code_123',
                redirect_uri='https://example.com/callback'
            )

            assert result['success'] is True
            assert result['access_token'] == 'new_access_token'

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_failure(self):
        """Test failed code exchange."""
        mock_error = {
            'error': {
                'message': 'Invalid code',
                'type': 'OAuthException',
                'code': 100
            }
        }

        with patch('aiohttp.ClientSession') as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 400
            mock_resp.json = AsyncMock(return_value=mock_error)

            mock_session_instance = MagicMock()
            mock_session_instance.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_resp)))
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await FacebookPublisher.exchange_code_for_token(
                app_id='test_app',
                app_secret='test_secret',
                code='invalid_code',
                redirect_uri='https://example.com/callback'
            )

            assert result['success'] is False
            assert 'Invalid code' in result['error']

    @pytest.mark.asyncio
    async def test_get_user_pages_success(self):
        """Test successful pages retrieval."""
        mock_response = {
            'data': [
                {
                    'id': '111111',
                    'name': 'Page One',
                    'access_token': 'token_1',
                    'category': 'Business'
                },
                {
                    'id': '222222',
                    'name': 'Page Two',
                    'access_token': 'token_2',
                    'category': 'Entertainment'
                }
            ]
        }

        with patch('aiohttp.ClientSession') as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)

            mock_session_instance = MagicMock()
            mock_session_instance.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_resp)))
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await FacebookPublisher.get_user_pages('test_token')

            assert result['success'] is True
            assert len(result['pages']) == 2
            assert result['pages'][0]['name'] == 'Page One'

    @pytest.mark.asyncio
    async def test_get_user_info_success(self):
        """Test successful user info retrieval."""
        mock_response = {
            'id': '123456789',
            'name': 'Test User'
        }

        with patch('aiohttp.ClientSession') as mock_session:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)

            mock_session_instance = MagicMock()
            mock_session_instance.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_resp)))
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await FacebookPublisher.get_user_info('test_token')

            assert result['success'] is True
            assert result['user_id'] == '123456789'
            assert result['user_name'] == 'Test User'
