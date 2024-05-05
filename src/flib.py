import requests
from bs4 import BeautifulSoup
import urllib.request
import urllib.parse
import os
import re

ALL_FORMATS = ['fb2', 'epub', 'mobi', 'pdf']
SITE = 'http://flibusta.is'


class Book:
    def __init__(self, book_id):
        self.id = book_id
        self.title = ''
        self.author = ''
        self.link = ''
        self.formats = {}
        self.cover = ''

    def __str__(self):
        return f'{self.title} - {self.author} ({self.id})'


def get_page(url):
    r = urllib.request.urlopen(url)
    html_bytes = r.read()
    html = html_bytes.decode("utf-8")
    parser = "html.parser"
    soup = BeautifulSoup(html, parser)
    return soup


def scrape_books(title: str) -> list[Book] | None:
    query_text = urllib.parse.quote(title)
    url_mask = "http://flibusta.is/booksearch?ask={request_str}&chb=on"
    url = url_mask.format(request_str=query_text)

    sp = get_page(url)

    target_div = sp.find('div', attrs={'class': 'clear-block', 'id': 'main'})
    target_ul_list = target_div.findChildren('ul', attrs={'class': ''})

    if len(target_ul_list) == 0:
        return None

    target_ul = target_ul_list[0]
    li_list = target_ul.find_all("li")

    link_list = [a for a in (("http://flibusta.is" + li.a.get('href') + '/') for li in li_list)]
    # author_list = [a for a in ((l.find_all('a')[1].text) for l in li_list)]
    author_list = []
    for li in li_list:
        a_list = li.find_all('a')
        if len(a_list) > 1:
            author_list_l = a_list[1:]
            author = ', '.join([a.text for a in author_list_l])
        else:
            author = '[автор не указан]'
        author_list.append(author)

    title_list = [a for a in ((li.find_all('a')[0].text) for li in li_list)]
    book_id_list = [str(li.a.get('href')).replace('/b/', '') for li in li_list]

    result = []
    for i in range(len(book_id_list)):
        book = Book(book_id_list[i])
        book.title = title_list[i]
        book.author = author_list[i]
        book.link = link_list[i]
        result.append(book)

    return result


def scrape_books_mbl(title: str, author: str) -> list[Book] | None:
    title_q = urllib.parse.quote(title)
    author_q = urllib.parse.quote(author)
    url = f"http://flibusta.is/makebooklist?ab=ab1&t={title_q}&ln={author_q}&sort=sd2&"

    sp = get_page(url)
    target_form = sp.find('form', attrs={'name': 'bk'})

    if target_form is None:
        return None

    div_list = target_form.find_all('div')

    link_list, title_list, book_id_list, author_list = [], [], [], []
    for d in div_list:
        b_href = d.find('a', attrs={'href': re.compile('/b/')}).get('href')
        link = "http://flibusta.is" + b_href + '/'
        link_list.append(link)

        title = d.find('a', attrs={'href': re.compile('/b/')}).text
        title_list.append(title)

        book_id = b_href.replace('/b/', '')
        book_id_list.append(book_id)

        a_list = d.find_all('a', attrs={'href': re.compile('/a/')})
        if len(a_list) > 1:
            author_list_l = a_list[1:]
            author = ', '.join([a.text for a in author_list_l[::-1]])
        else:
            author = '[автор не указан]'
        author_list.append(author)

    result = []
    for i in range(len(book_id_list)):
        book = Book(book_id_list[i])
        book.title = title_list[i]
        book.author = author_list[i]
        book.link = link_list[i]
        result.append(book)

    return result


def get_book_by_id(book_id):
    book = Book(book_id)
    book.link = SITE + '/b/' + book_id + '/'

    sp = get_page(book.link)
    target_div = sp.find('div', attrs={'class': 'clear-block', 'id': 'main'})

    target_h1 = target_div.find('h1', attrs={'class': 'title'})
    book.title = target_h1.text

    target_img = target_div.find('img', attrs={'alt': 'Cover image'})
    if target_img:
        book.cover = SITE + target_img.get('src')
    else:
        book.cover = None

    format_li_list = target_div.find_all('a', string=re.compile(r'\(.*fb2\)|\(.*epub\)|\(.*mobi\)|\(.*pdf\)|\(.*djvu\)'))
    for a in format_li_list:
        b_format = a.text
        link = a.get('href')
        book.formats[b_format] = SITE + link

    book.author = target_h1.findNext('a').text

    return book


def download_book_cover(book):
    c_response = requests.get(book.cover)
    c_full_path = os.path.join(os.getcwd(), "books", book.id, 'cover.jpg')
    os.makedirs(os.path.dirname(c_full_path), exist_ok=True)
    open(os.path.join(c_full_path), "wb").write(c_response.content)


def download_book(book: Book, b_format):
    book_url = book.formats[b_format]

    try:
        b_response = requests.get(book_url, timeout=10)
    except requests.exceptions.Timeout as e:
        return None

    if not b_response.ok:
        return None

    n_index = str(b_response.headers['content-disposition']).index('=')
    b_filename = b_response.headers['content-disposition'][n_index + 1::].replace('\"', '')
    if b_filename.endswith('.fb2.zip'):
        b_filename = b_filename.removesuffix('.zip')

    return b_response.content, b_filename
