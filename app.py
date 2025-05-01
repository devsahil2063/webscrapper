from flask import Flask, request, jsonify
from flask_cors import CORS
from bs4 import BeautifulSoup
import requests
import re
import json
import urllib.parse

app = Flask(__name__)
CORS(app)

def is_valid_url(url):
    regex = re.compile(
        r'^https?://'  
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return re.match(regex, url) is not None

def fetch_content(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=10)
        return res.text
    except Exception as e:
        return f"Error fetching content: {str(e)}"

def fetch_css_files(soup, base_url):
    css_content = []
    for style_tag in soup.find_all('style'):
        if style_tag.string:
            css_content.append(style_tag.string)
    for link in soup.find_all('link', rel='stylesheet'):
        href = link.get('href')
        if href:
            css_url = urllib.parse.urljoin(base_url, href)
            css_data = fetch_content(css_url)
            if not css_data.startswith('Error'):
                css_content.append(css_data)
    return '\n'.join(css_content)

def parse_tailwind_styles(css_content):
    tailwind_styles = {}
    pattern = r'\.([^{]+?)\s*{([^}]+?)}'
    matches = re.finditer(pattern, css_content, re.DOTALL)
    for match in matches:
        class_name = match.group(1).strip()
        class_name = re.sub(r'\\([.:])', r'\1', class_name)
        properties = match.group(2).strip()
        properties = '; '.join(prop.strip() for prop in properties.split(';') if prop.strip())
        if properties:
            tailwind_styles[class_name] = properties
    return tailwind_styles

def tailwind_to_css(tailwind_classes, tailwind_styles):
    css_styles = []
    remaining_classes = []
    for cls in tailwind_classes:
        if cls in tailwind_styles:
            css_styles.append(tailwind_styles[cls])
        else:
            remaining_classes.append(cls)
    return '; '.join(css_styles), remaining_classes

def get_element_attributes(element, tailwind_styles):
    attributes = {}
    class_list = element.get('class', [])
    if class_list:
        css_style, remaining_classes = tailwind_to_css(class_list, tailwind_styles)
        if remaining_classes:
            attributes['class'] = remaining_classes
        if css_style:
            existing_style = element.get('style', '')
            attributes['style'] = f"{existing_style}; {css_style}" if existing_style else css_style
    if element.get('id'):
        attributes['id'] = element.get('id')
    return attributes if attributes else {}

def parse_head(head_tag, tailwind_styles):
    head_structure = {
        'attributes': get_element_attributes(head_tag, tailwind_styles),
        'children': []
    }
    for child in head_tag.children:
        if child.name:
            child_data = {
                'tag': child.name,
                'attributes': get_element_attributes(child, tailwind_styles),
                'content': child.get_text(strip=True) or ''
            }
            if child.name == 'style':
                child_data['content'] = child.string or ''
            head_structure['children'].append(child_data)
    return head_structure

def parse_body(body_tag, tailwind_styles):
    body_structure = {
        'attributes': get_element_attributes(body_tag, tailwind_styles),
        'children': []
    }
    def parse_element(element):
        element_data = {
            'tag': element.name,
            'attributes': get_element_attributes(element, tailwind_styles),
            'content': element.get_text(strip=True) or ''
        }
        children = []
        for child in element.children:
            if child.name:
                children.append(parse_element(child))
        if children:
            element_data['children'] = children
        return element_data
    for child in body_tag.children:
        if child.name:
            body_structure['children'].append(parse_element(child))
    return body_structure

def parse_html_to_json(html_content, tailwind_styles):
    soup = BeautifulSoup(html_content, 'html.parser')
    html_tag = soup.html
    if html_tag:
        return {
            'html': {
                'attributes': get_element_attributes(html_tag, tailwind_styles),
                'head': parse_head(soup.head, tailwind_styles) if soup.head else {},
                'body': parse_body(soup.body, tailwind_styles) if soup.body else {}
            }
        }
    return {'error': 'No <html> tag found'}

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.get_json()
    url = data.get('url')
    mode = data.get('mode', 'html')
    if not url or not is_valid_url(url):
        return jsonify({'error': 'Invalid URL'}), 400
    html_content = fetch_content(url)
    if html_content.startswith("Error"):
        return jsonify({'error': html_content}), 500
    soup = BeautifulSoup(html_content, 'html.parser')
    css_content = fetch_css_files(soup, url)
    tailwind_styles = parse_tailwind_styles(css_content)
    if mode == "json":
        parsed = parse_html_to_json(html_content, tailwind_styles)
        return jsonify(parsed)
    else:
        return jsonify({'html': html_content})

if __name__ == '__main__':
    app.run()
