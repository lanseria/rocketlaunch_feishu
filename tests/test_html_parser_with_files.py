import pytest
import os
from bs4 import BeautifulSoup
# 假设 pytest 从项目根目录运行，并且 pyproject.toml 中有 pythonpath = ["src"]
# 或者您已经 pip install -e .
from rocketlaunch_feishu.html_parser import _parse_launch_status_from_style

# Helper function to get the path to test data files
def get_test_data_path(filename):
    # Assumes this test file is in 'tests/' and test data is in 'tests/test_data/html_samples/'
    dir_path = os.path.dirname(os.path.realpath(__file__))
    return os.path.join(dir_path, "test_data", "html_samples", filename)

def extract_style_from_html_file(html_file_path: str) -> str | None:
    """Reads an HTML file, parses it, and extracts the style attribute of the first launch card."""
    if not os.path.exists(html_file_path):
        print(f"Warning: Test HTML file not found: {html_file_path}")
        return None
    with open(html_file_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    soup = BeautifulSoup(html_content, 'html.parser')
    # Find the specific div we are interested in
    # Adjust the selector if your actual card structure is different or more specific
    launch_card = soup.find('div', class_=lambda x: x and 'launch' in x.split() and 'mdl-card' in x.split())
    
    if launch_card:
        return launch_card.get('style')
    return None

# Test cases using HTML files
# Each tuple: (test_name, html_filename, expected_status)
html_file_test_data = [
    ("from_file_success", "sample_success.html", "Success"),
    ("from_file_failure", "sample_failure.html", "Failure"),
    ("from_file_partial", "sample_partial.html", "Partial Success"),
    ("from_file_unknown_rgba", "sample_unknown_rgba.html", "Unknown"),
    ("from_file_no_border_color", "sample_no_border_color.html", "Unknown"),
]

@pytest.mark.parametrize("test_name, html_filename, expected", html_file_test_data)
def test_parse_status_from_html_file(test_name, html_filename, expected):
    html_file_path = get_test_data_path(html_filename)
    style_attribute = extract_style_from_html_file(html_file_path)
    
    # If style_attribute is None (e.g., file not found or card not found), the test should reflect that
    # _parse_launch_status_from_style handles None input and returns "Unknown"
    assert _parse_launch_status_from_style(style_attribute) == expected, f"Test failed for: {test_name}"

# You can also keep your direct string-based tests for focused unit testing
direct_string_test_data = [
    ("direct_success_exact_hex", "border-color: #45CF5D;", "Success"),
    ("direct_failure_hex_from_example", "border-color: #DA3432;", "Failure"),
    ("direct_partial_success_exact_hex", "border-color: #FF9900;", "Partial Success"),
    ("direct_rgba_white_border", "border-color: rgba(255,255,255,0.8);", "Unknown"),
    ("direct_no_border_color_style", "font-weight: bold; color: red;", "Unknown"),
    ("direct_empty_style", "", "Unknown"),
    ("direct_none_style", None, "Unknown"),
    ("direct_unknown_hex_color", "border-color: #123456;", "Unknown"),
]

@pytest.mark.parametrize("test_name, input_style, expected", direct_string_test_data)
def test_parse_launch_status_direct_string(test_name, input_style, expected):
    assert _parse_launch_status_from_style(input_style) == expected, f"Test failed for: {test_name}"