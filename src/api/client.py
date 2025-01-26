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

    def check_if_rate_limited(self, response: requests.Response) -> bool:
        """Check if the response indicates rate limiting"""
        if 'results' not in response.json():
            wait_time_in_seconds = response.headers['Retry-After']
            time.sleep(int(wait_time_in_seconds) + 3)
            return True
        return False

    def make_request(self, params: Dict) -> requests.Response:
        """Make a request to the Readwise API"""
        return requests.get(
            url=self.base_url,
            params=params,
            headers={"Authorization": f"Token {self.token}"},
            verify=False
        )

    def calculate_params(self, next_page_cursor: Optional[str], location: str) -> Dict:
        """Calculate request parameters"""
        params = {}
        if next_page_cursor:
            params['pageCursor'] = next_page_cursor
        if location:
            params['location'] = location
        return params

    def fetch_reader_document_list(self, location: str) -> List[Dict]:
        """Fetch all documents from the Readwise Reader API for a given location"""
        urllib3.disable_warnings()
        full_data = []
        next_page_cursor = None
        
        while True:
            params = self.calculate_params(next_page_cursor, location)
            response = self.make_request(params)
            
            if self.check_if_rate_limited(response):
                response = self.make_request(params)
                
            full_data.extend(response.json()['results'])
            next_page_cursor = response.json().get('nextPageCursor')
            
            if not next_page_cursor:
                break
        
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