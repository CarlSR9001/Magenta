"""Webpage fetch tool using Jina AI reader.

Allows the agent to fetch and read web pages, converting them to
clean markdown text. Uses Jina AI's free reader service which
handles JavaScript rendering and content extraction.
"""

from pydantic import BaseModel, Field


class FetchWebpageArgs(BaseModel):
    """Arguments for the fetch_webpage tool."""
    url: str = Field(
        ..., 
        description="The URL of the webpage to fetch and convert to markdown/text format"
    )
    max_length: int = Field(
        default=10000,
        description="Maximum number of characters to return (default 10000)"
    )


def fetch_webpage(url: str, max_length: int = 10000) -> str:
    """
    Fetch a webpage and convert it to markdown/text format using Jina AI reader.
    
    This tool allows you to read websites, documentation, articles, and other
    web content. The content is returned as clean markdown text with images
    stripped out.
    
    Args:
        url: The URL of the webpage to fetch and convert
        max_length: Maximum number of characters to return (default 10000)
        
    Returns:
        String containing the webpage content in markdown/text format,
        truncated to max_length if necessary
    """
    import requests
    
    try:
        # Construct the Jina AI reader URL
        # Jina AI fetches the page, renders JS, and extracts clean text
        jina_url = f"https://r.jina.ai/{url}"
        
        # Make the request to Jina AI
        headers = {
            "Accept": "text/plain",
            "User-Agent": "Magenta-Agent/1.0"
        }
        response = requests.get(jina_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        content = response.text
        
        # Truncate if necessary
        if len(content) > max_length:
            content = content[:max_length] + f"\n\n[Content truncated at {max_length} characters]"
        
        return content
        
    except requests.exceptions.Timeout:
        return f"Error: Request timed out while fetching {url}"
    except requests.exceptions.RequestException as e:
        return f"Error fetching webpage: {str(e)}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"
