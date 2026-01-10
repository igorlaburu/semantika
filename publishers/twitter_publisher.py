"""Twitter publisher for semantika articles."""

import aiohttp
import asyncio
from typing import Dict, Any, Optional, List
import json
import re
from urllib.parse import urlparse
import hashlib
import hmac
import base64
import urllib.parse
import time
import secrets

from .base_publisher import BasePublisher, PublicationResult
from utils.logger import get_logger

logger = get_logger("twitter_publisher")


class TwitterPublisher(BasePublisher):
    """Twitter API v2 publisher."""
    
    def get_platform_type(self) -> str:
        return "twitter"
    
    def _get_api_url(self, endpoint: str) -> str:
        """Build Twitter API v2 URL."""
        return f"https://api.twitter.com/2/{endpoint}"
    
    def _generate_oauth1_header(self, method: str, url: str, params: Dict[str, str] = None) -> str:
        """Generate OAuth 1.0a authorization header for Twitter API."""
        api_key = self.credentials.get('api_key')
        api_secret = self.credentials.get('api_secret')
        access_token = self.credentials.get('access_token')
        access_token_secret = self.credentials.get('access_token_secret')
        
        if not all([api_key, api_secret, access_token, access_token_secret]):
            raise ValueError("Twitter requires 'api_key', 'api_secret', 'access_token', and 'access_token_secret' in credentials")
        
        # OAuth 1.0a parameters
        oauth_params = {
            'oauth_consumer_key': api_key,
            'oauth_token': access_token,
            'oauth_signature_method': 'HMAC-SHA1',
            'oauth_timestamp': str(int(time.time())),
            'oauth_nonce': secrets.token_hex(16),
            'oauth_version': '1.0'
        }
        
        # Combine OAuth params with request params
        all_params = {**oauth_params}
        if params:
            all_params.update(params)
        
        # Create signature base string
        normalized_params = '&'.join([
            f'{urllib.parse.quote_plus(str(k))}={urllib.parse.quote_plus(str(v))}'
            for k, v in sorted(all_params.items())
        ])
        
        base_string = f'{method.upper()}&{urllib.parse.quote_plus(url)}&{urllib.parse.quote_plus(normalized_params)}'
        
        # Create signing key
        signing_key = f'{urllib.parse.quote_plus(api_secret)}&{urllib.parse.quote_plus(access_token_secret)}'
        
        # Generate signature
        signature = base64.b64encode(
            hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
        ).decode()
        
        oauth_params['oauth_signature'] = signature
        
        # Build authorization header
        auth_header = 'OAuth ' + ', '.join([
            f'{k}="{urllib.parse.quote_plus(str(v))}"'
            for k, v in sorted(oauth_params.items())
        ])
        
        return auth_header
    
    def _split_into_tweets(self, content: str, max_length: int = 280) -> List[str]:
        """Split long content into tweet-sized chunks."""
        # Remove HTML tags for Twitter
        clean_content = re.sub(r'<[^>]+>', '', content)
        clean_content = clean_content.strip()
        
        # If content fits in one tweet
        if len(clean_content) <= max_length:
            return [clean_content]
        
        # Split content into sentences
        sentences = re.split(r'[.!?]+', clean_content)
        tweets = []
        current_tweet = ""
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            
            # Add sentence to current tweet if it fits
            test_tweet = f"{current_tweet} {sentence}." if current_tweet else f"{sentence}."
            
            if len(test_tweet) <= max_length - 10:  # Leave space for thread numbering
                current_tweet = test_tweet
            else:
                # Current tweet is full, start new one
                if current_tweet:
                    tweets.append(current_tweet)
                current_tweet = f"{sentence}."
                
                # If single sentence is too long, truncate it
                if len(current_tweet) > max_length - 10:
                    current_tweet = current_tweet[:max_length - 13] + "..."
        
        # Add last tweet
        if current_tweet:
            tweets.append(current_tweet)
        
        # Add thread numbering if multiple tweets
        if len(tweets) > 1:
            numbered_tweets = []
            for i, tweet in enumerate(tweets, 1):
                numbered_tweets.append(f"{i}/{len(tweets)} {tweet}")
            return numbered_tweets
        
        return tweets
    
    def _extract_hashtags_and_mentions(self, tags: List[str]) -> str:
        """Convert article tags to Twitter hashtags."""
        if not tags:
            return ""
        
        # Convert tags to valid hashtags
        hashtags = []
        for tag in tags[:5]:  # Limit to 5 hashtags
            # Clean tag and make it hashtag-safe
            clean_tag = re.sub(r'[^a-zA-Z0-9áéíóúñüÁÉÍÓÚÑÜ]', '', tag)
            if clean_tag and len(clean_tag) > 1:
                hashtags.append(f"#{clean_tag}")
        
        return " ".join(hashtags) if hashtags else ""
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test Twitter connection and authentication."""
        try:
            url = self._get_api_url("users/me")
            headers = {
                'Authorization': self._generate_oauth1_header('GET', url),
                'Content-Type': 'application/json'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        username = data.get('data', {}).get('username', 'unknown')
                        return {
                            "success": True,
                            "message": f"Successfully connected to Twitter as @{username}",
                            "details": {
                                "username": username,
                                "user_id": data.get('data', {}).get('id')
                            }
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "success": False,
                            "message": f"Twitter API returned status {response.status}",
                            "details": {"error": error_text}
                        }
                        
        except Exception as e:
            logger.error("twitter_test_connection_error", error=str(e))
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}"
            }
    
    async def publish_article(
        self,
        title: str,
        content: str,
        excerpt: Optional[str] = None,
        tags: Optional[list] = None,
        image_url: Optional[str] = None,
        status: str = "publish",
        slug: Optional[str] = None,
        category: Optional[str] = None,
        fecha_publicacion: Optional[str] = None,
        imagen_uuid: Optional[str] = None,
        temp_image_path: Optional[str] = None
    ) -> PublicationResult:
        """Publish article to Twitter as a thread."""
        try:
            # Build tweet content
            tweet_content = f"📰 {title}\n\n"
            
            # Add excerpt or first part of content
            if excerpt:
                tweet_content += f"{excerpt}\n\n"
            else:
                # Use first paragraph of content
                clean_content = re.sub(r'<[^>]+>', '', content)
                first_para = clean_content.split('\n\n')[0][:200]
                tweet_content += f"{first_para}...\n\n"
            
            # Add hashtags
            hashtags = self._extract_hashtags_and_mentions(tags or [])
            if hashtags:
                tweet_content += hashtags
            
            # Split into tweets if necessary
            tweets = self._split_into_tweets(tweet_content)
            
            logger.info("twitter_publish_start", 
                title=title[:50], 
                tweets_count=len(tweets),
                has_image=bool(temp_image_path or image_url)
            )
            
            # TODO: Upload image if provided
            media_id = None
            if temp_image_path:
                # We'll implement image upload in next iteration
                logger.info("twitter_image_upload_pending", image_path=temp_image_path)
            
            # Publish tweets in thread
            tweet_ids = []
            reply_to_id = None
            
            for i, tweet_text in enumerate(tweets):
                result = await self._post_tweet(tweet_text, reply_to_id, media_id if i == 0 else None)
                
                if result.get('success'):
                    tweet_id = result['data']['id']
                    tweet_ids.append(tweet_id)
                    reply_to_id = tweet_id  # Next tweet replies to this one
                    
                    logger.info("twitter_tweet_posted", 
                        tweet_number=i+1,
                        tweet_id=tweet_id,
                        reply_to=reply_to_id if i > 0 else None
                    )
                else:
                    # If any tweet fails, stop the thread
                    logger.error("twitter_tweet_failed", 
                        tweet_number=i+1,
                        error=result.get('error')
                    )
                    break
            
            if tweet_ids:
                # Build Twitter URL for first tweet
                username = self.base_url.replace('@', '') if self.base_url.startswith('@') else self.base_url
                first_tweet_url = f"https://twitter.com/{username}/status/{tweet_ids[0]}"
                
                return PublicationResult(
                    success=True,
                    url=first_tweet_url,
                    external_id=tweet_ids[0],
                    metadata={
                        "thread_ids": tweet_ids,
                        "tweets_count": len(tweet_ids),
                        "username": username,
                        "platform": "twitter"
                    }
                )
            else:
                return PublicationResult(
                    success=False,
                    error="Failed to post any tweets"
                )
                
        except Exception as e:
            logger.error("twitter_publish_error", 
                title=title[:50],
                error=str(e)
            )
            return PublicationResult(
                success=False,
                error=f"Twitter publish failed: {str(e)}"
            )
    
    async def _post_tweet(self, text: str, reply_to_id: Optional[str] = None, media_id: Optional[str] = None) -> Dict[str, Any]:
        """Post a single tweet."""
        try:
            url = self._get_api_url("tweets")
            
            # Build tweet data
            tweet_data = {"text": text}
            
            if reply_to_id:
                tweet_data["reply"] = {"in_reply_to_tweet_id": reply_to_id}
            
            if media_id:
                tweet_data["media"] = {"media_ids": [media_id]}
            
            headers = {
                'Authorization': self._generate_oauth1_header('POST', url),
                'Content-Type': 'application/json'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=tweet_data) as response:
                    response_data = await response.json()
                    
                    if response.status == 201:
                        return {
                            "success": True,
                            "data": response_data["data"]
                        }
                    else:
                        return {
                            "success": False,
                            "error": response_data.get('detail', f'HTTP {response.status}'),
                            "response": response_data
                        }
                        
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def sanitize_content(self, content: str) -> str:
        """Clean HTML content for Twitter."""
        # Remove HTML tags
        clean = re.sub(r'<[^>]+>', '', content)
        # Normalize whitespace
        clean = re.sub(r'\s+', ' ', clean)
        return clean.strip()
    
    def format_tags(self, tags: list) -> str:
        """Format tags as Twitter hashtags."""
        return self._extract_hashtags_and_mentions(tags)