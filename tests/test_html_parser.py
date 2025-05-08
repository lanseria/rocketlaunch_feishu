import pytest
from src.rocketlaunch_feishu.html_parser import _parse_launch_status_from_style # Adjust import path if necessary

# Parameterized test cases
# Each tuple: (test_name, input_style_string, expected_status)
test_data = [
    ("success_exact_hex", "border-color: #45CF5D;", "Success"),
    ("success_hex_with_other_styles", "color: black; border-color: #45cf5d; font-weight: bold;", "Success"),
    ("success_hex_lowercase", "border-color: #45cf5d;", "Success"),
    ("success_hex_no_space_after_colon", "border-color:#45CF5D;", "Success"),
    
    ("failure_exact_hex", "border-color: #DA3432;", "Failure"),
    ("failure_hex_from_example", "border-color: #DA3432; border-style: solid; border-width: 5px;", "Failure"),
    ("failure_hex_lowercase", "border-color: #da3432;", "Failure"),

    ("partial_success_exact_hex", "border-color: #FF9900;", "Partial Success"),
    ("partial_success_hex_lowercase", "border-color: #ff9900;", "Partial Success"),
    ("partial_success_with_spaces", "border-color :  #FF9900 ;", "Partial Success"),

    ("rgba_white_border", "border-color: rgba(255,255,255,0.8);", "Unknown"), # As per current logic
    ("no_border_color_style", "font-weight: bold; color: red;", "Unknown"),
    ("empty_style", "", "Unknown"),
    ("none_style", None, "Unknown"),
    ("malformed_border_color", "border-color: ;", "Unknown"), # Regex might not match or match empty
    ("unknown_hex_color", "border-color: #123456;", "Unknown"),
    ("different_style_property", "background-color: #DA3432;", "Unknown"),
    ("mixed_case_property_name", "Border-Color: #DA3432;", "Failure"), # re.IGNORECASE handles this
    ("extra_whitespace_in_value", "border-color:    #DA3432   ;", "Failure"), # .strip() handles this
]

@pytest.mark.parametrize("test_name, input_style, expected", test_data)
def test_parse_launch_status(test_name, input_style, expected):
    assert _parse_launch_status_from_style(input_style) == expected, f"Test failed for: {test_name}"

# Example of how you might have discovered the issue (manual test inside the file)
if __name__ == '__main__':
    # Test cases based on your problem description
    style_failure_from_html = "border-color: #DA3432; border-style: solid; border-width: 5px;"
    print(f"Input: '{style_failure_from_html}', Parsed: '{_parse_launch_status_from_style(style_failure_from_html)}' (Expected: Failure)")

    style_success_similar = """border-color:
				
	                #45CF5D; border-style: solid; border-width: 5px;
                
				"""
    print(f"Input: '{style_success_similar}', Parsed: '{_parse_launch_status_from_style(style_success_similar)}' (Expected: Success)")
    
    style_partial_similar = "border-color: #FF9900; border-style: solid; border-width: 5px;"
    print(f"Input: '{style_partial_similar}', Parsed: '{_parse_launch_status_from_style(style_partial_similar)}' (Expected: Partial Success)")

    style_rgba_white = "border-color: rgba(255,255,255,0.8);"
    print(f"Input: '{style_rgba_white}', Parsed: '{_parse_launch_status_from_style(style_rgba_white)}' (Expected: Unknown)")
    
    style_unknown_hex = "border-color: #ABCDEF;"
    print(f"Input: '{style_unknown_hex}', Parsed: '{_parse_launch_status_from_style(style_unknown_hex)}' (Expected: Unknown)")
    
    no_border_color = "border-style: solid; border-width: 5px;"
    print(f"Input: '{no_border_color}', Parsed: '{_parse_launch_status_from_style(no_border_color)}' (Expected: Unknown)")