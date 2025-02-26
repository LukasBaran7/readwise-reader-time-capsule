import os
from typing import Optional, List, Dict
import requests
import time
import urllib3

from ..models.page import Page, Result
from ..utils.logger import logger

class ReadwiseClient:
    def __init__(self, token: str):
        self.token = token
        self.base_url = "https://readwise.io/api/v3/list/"
        self.request_count = 0

    def check_if_rate_limited(self, response: requests.Response) -> bool:
        """Check if the response indicates rate limiting"""
        if 'results' not in response.json():
            wait_time_in_seconds = response.headers['Retry-After']
            time.sleep(int(wait_time_in_seconds) + 3)
            return True
        return False

    def make_request(self, params: Dict) -> requests.Response:
        """Make a request to the Readwise API"""
        self.request_count += 1
        
        # Log basic request info
        with_html = 'withHtmlContent' in params and params['withHtmlContent'] == 'true'
        logger.info(f"Making Readwise API request #{self.request_count}: with_html={with_html}")
        
        start_time = time.time()
        response = requests.get(
            url=self.base_url,
            params=params,
            headers={"Authorization": f"Token {self.token}"},
            verify=False
        )
        elapsed_time = time.time() - start_time
        
        # Log basic response info
        status = response.status_code
        logger.info(f"Received response #{self.request_count}: status={status}, time={elapsed_time:.2f}s")
        
        return response

    def calculate_params(self, next_page_cursor: Optional[str], location: str, with_html_content: bool = False) -> Dict:
        """Calculate request parameters"""
        params = {}
        if next_page_cursor:
            params['pageCursor'] = next_page_cursor
        if location:
            params['location'] = location
        if with_html_content:
            params['withHtmlContent'] = 'true'
        return params

    def fetch_reader_document_list(self, location: str, limit: int = None, with_html_content: bool = False) -> List[Dict]:
        """Fetch documents from the Readwise Reader API for a given location
        
        Args:
            location: The location to fetch documents from ('later', 'archive', etc.)
            limit: Maximum number of documents to fetch (None for all)
            with_html_content: Whether to include HTML content in the response
        """
        urllib3.disable_warnings()
        full_data = []
        next_page_cursor = None
        page_count = 0
        
        logger.info(f"Starting document fetch: location={location}, limit={limit}, with_html={with_html_content}")
        
        while True:
            # If we already have enough data, break early
            if limit is not None and len(full_data) >= limit:
                break
            
            # Calculate how many more items we need if there's a limit
            remaining = None
            if limit is not None:
                remaining = limit - len(full_data)
                if remaining <= 0:
                    break
            
            page_count += 1
            
            params = self.calculate_params(next_page_cursor, location, with_html_content)
            response = self.make_request(params)
            
            if self.check_if_rate_limited(response):
                response = self.make_request(params)
            
            results = response.json().get('results', [])
            
            # Only add up to the limit
            if limit is not None and len(full_data) + len(results) > limit:
                results = results[:remaining]
            
            full_data.extend(results)
            
            # If we've reached the limit or there's no next page, break
            if limit is not None and len(full_data) >= limit:
                break
            
            next_page_cursor = response.json().get('nextPageCursor')
            if not next_page_cursor:
                break
        
        logger.info(f"Fetch complete: {len(full_data)} documents retrieved in {page_count} pages")
        return full_data

    def fetch_single_page(self, next_page_cursor: Optional[str] = None, location: str = 'later') -> Optional[Page]:
        """Fetch a single page of results from the Readwise Reader API"""
        urllib3.disable_warnings()
        params = self.calculate_params(next_page_cursor, location)
        response = self.make_request(params)
        
        if self.check_if_rate_limited(response):
            response = self.make_request(params)

        response_json = response.json()
        
        return Page(
            count=response_json['count'],
            nextPageCursor=response_json['nextPageCursor'],
            results=[Result(**result) for result in response_json['results']]
        )