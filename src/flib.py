import os
import re
import urllib.parse

import httpx
from bs4 import BeautifulSoup


ALL_FORMATS = ["fb2", "epub", "mobi", "pdf", "djvu"]
SITE = "http://flibusta.is"

HTTP_TIMEOUT = 10.0


class Book:
    def __init__(self, book_id):
        self.id = book_id
        self.title = ""
        self.author = ""
        self.link = ""
        self.formats = {}
        self.cover = ""
        self.size = ""
        self.annotation = ""

    def __str__(self):
        return f"{self.title} - {self.author} ({self.id})"


async def get_page(url: str) -> BeautifulSoup:
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()

    html = response.text

    return BeautifulSoup(html, "html.parser")


async def scrape_books_by_title(text: str) -> list[Book] | None:
    query_text = urllib.parse.quote(text)
    url = f"{SITE}/booksearch?ask={query_text}&chb=on"

    sp = await get_page(url)

    target_div = sp.find(
        "div",
        attrs={"class": "clear-block", "id": "main"},
    )

    if target_div is None:
        return None

    target_ul_list = target_div.findChildren(
        "ul",
        attrs={"class": ""},
    )

    if len(target_ul_list) == 0:
        return None

    target_ul = target_ul_list[0]
    li_list = target_ul.find_all("li")

    link_list = [
        SITE + li.a.get("href") + "/"
        for li in li_list
    ]

    author_list = []

    for li in li_list:
        a_list = li.find_all("a")

        if len(a_list) > 1:
            author_list_l = a_list[1:]
            author = ", ".join(
                a.text for a in author_list_l
            )
        else:
            author = "[автор не указан]"

        author_list.append(author)

    title_list = [
        li.find_all("a")[0].text
        for li in li_list
    ]

    book_id_list = [
        str(li.a.get("href")).replace("/b/", "")
        for li in li_list
    ]

    result = []

    for i in range(len(book_id_list)):
        book = Book(book_id_list[i])
        book.title = title_list[i]
        book.author = author_list[i]
        book.link = link_list[i]

        result.append(book)

    return result


async def scrape_books_by_author(
    text: str,
) -> list[list[Book]] | None:
    query_text = urllib.parse.quote(text)
    url = f"{SITE}/booksearch?ask={query_text}&cha=on"

    sp = await get_page(url)

    target_div = sp.find(
        "div",
        attrs={"class": "clear-block", "id": "main"},
    )

    if target_div is None:
        return None

    target_ul_list = target_div.findChildren(
        "ul",
        attrs={"class": ""},
    )

    if len(target_ul_list) == 0:
        return None

    target_ul = target_ul_list[0]
    li_list = target_ul.find_all("li")

    authors_link_list = [
        SITE + li.a.get("href") + "/"
        for li in li_list
    ]

    final_res = []

    for author_link in authors_link_list:
        sp_2 = await get_page(author_link)

        author_element = sp_2.find(
            "h1",
            attrs={"class": "title"},
        )

        if author_element is None:
            continue

        author = author_element.text

        target_form = sp_2.find(
            "form",
            attrs={"method": "POST"},
        )

        if target_form is None:
            continue

        target_p_translates = target_form.find(
            "h3",
            string="Переводы",
        )

        if target_p_translates:
            sibling = target_p_translates.next_sibling

            while sibling:
                next_sibling = sibling.next_sibling
                sibling.extract()
                sibling = next_sibling

        target_checkbox_list_2 = target_form.findChildren("svg")
        target_a_list_2 = []

        for cb in target_checkbox_list_2:
            element = cb.find_next_sibling("a")

            if element:
                target_a_list_2.append(element)

        if len(target_a_list_2) == 0:
            continue

        books_list_2 = [
            SITE + a.get("href") + "/"
            for a in target_a_list_2
        ]

        title_list = [
            a.text
            for a in target_a_list_2
        ]

        book_id_list = [
            str(a.get("href")).replace("/b/", "")
            for a in target_a_list_2
        ]

        result = []

        for i in range(len(book_id_list)):
            book = Book(book_id_list[i])
            book.title = title_list[i]
            book.author = author
            book.link = books_list_2[i]

            result.append(book)

        final_res.append(result)

    return final_res


async def scrape_books_mbl(
    title: str,
    author: str,
) -> list[Book] | None:
    title_q = urllib.parse.quote(title)
    author_q = urllib.parse.quote(author)

    url = (
        f"{SITE}/makebooklist"
        f"?ab=ab1"
        f"&t={title_q}"
        f"&ln={author_q}"
        f"&sort=sd2"
    )

    sp = await get_page(url)

    target_form = sp.find(
        "form",
        attrs={"name": "bk"},
    )

    if target_form is None:
        return None

    div_list = target_form.find_all("div")

    link_list = []
    title_list = []
    book_id_list = []
    author_list = []

    for div in div_list:
        book_link_element = div.find(
            "a",
            attrs={"href": re.compile("/b/")},
        )

        if book_link_element is None:
            continue

        b_href = book_link_element.get("href")

        link = SITE + b_href + "/"
        link_list.append(link)

        book_title = book_link_element.text
        title_list.append(book_title)

        book_id = b_href.replace("/b/", "")
        book_id_list.append(book_id)

        a_list = div.find_all(
            "a",
            attrs={"href": re.compile("/a/")},
        )

        if len(a_list) == 1:
            book_author = a_list[0].text
        elif len(a_list) > 1:
            author_list_l = a_list[1:]
            book_author = ", ".join(
                a.text for a in author_list_l[::-1]
            )
        else:
            book_author = "[автор не указан]"

        author_list.append(book_author)

    result = []

    for i in range(len(book_id_list)):
        book = Book(book_id_list[i])
        book.title = title_list[i]
        book.author = author_list[i]
        book.link = link_list[i]

        result.append(book)

    return result


async def get_book_by_id(book_id: str) -> Book | None:
    book = Book(book_id)
    book.link = f"{SITE}/b/{book_id}/"

    sp = await get_page(book.link)

    target_div = sp.find(
        "div",
        attrs={"class": "clear-block", "id": "main"},
    )

    if target_div is None:
        return None

    target_h1 = target_div.find(
        "h1",
        attrs={"class": "title"},
    )

    if target_h1 is None:
        return None

    book.title = target_h1.text

    if book.title == "Книги":
        return None

    size_element = sp.find(
        "span",
        attrs={"style": "size"},
    )

    if size_element:
        book.size = size_element.text

    target_img = target_div.find(
        "img",
        attrs={"alt": "Cover image"},
    )

    if target_img:
        book.cover = SITE + target_img.get("src")
    else:
        book.cover = None

    format_li_list = target_div.find_all(
        "a",
        string=re.compile(
            r"\(.*fb2\)|\(.*epub\)|\(.*mobi\)|\(.*pdf\)|\(.*djvu\)"
        ),
    )

    for a in format_li_list:
        book_format = a.text
        link = a.get("href")

        book.formats[book_format] = SITE + link

    author_element = target_h1.findNext("a")

    if author_element:
        book.author = author_element.text

    book.annotation = ""

    annotation_header = target_div.find(
        "h2",
        string=re.compile(
            "Аннотация",
            re.IGNORECASE,
        ),
    )

    if annotation_header:
        annotation_paragraphs = []

        sibling = annotation_header.find_next_sibling()

        while sibling and sibling.name != "h2":
            if sibling.name == "p" and sibling.text.strip():
                annotation_paragraphs.append(
                    sibling.text.strip()
                )

            sibling = sibling.find_next_sibling()

        book.annotation = "\n\n".join(
            annotation_paragraphs
        )
    else:
        first_p = target_h1.find_next_sibling("p")

        if first_p and first_p.text.strip():
            book.annotation = first_p.text.strip()

    return book


async def download_book_cover(book: Book):
    if not book.cover:
        return

    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
    ) as client:
        response = await client.get(book.cover)
        response.raise_for_status()

    c_full_path = os.path.join(
        os.getcwd(),
        "books",
        book.id,
        "cover.jpg",
    )

    os.makedirs(
        os.path.dirname(c_full_path),
        exist_ok=True,
    )

    with open(c_full_path, "wb") as file:
        file.write(response.content)


async def download_book(
    book: Book,
    b_format: str,
):
    book_url = book.formats[b_format]

    try:
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            follow_redirects=True,
        ) as client:
            response = await client.get(book_url)
    except httpx.TimeoutException:
        return None

    if not response.is_success:
        return None

    content_disposition = response.headers.get(
        "content-disposition"
    )

    if not content_disposition:
        return None

    try:
        n_index = content_disposition.index("=")
    except ValueError:
        return None

    filename = content_disposition[
        n_index + 1:
    ].replace('"', "")

    if filename.endswith(".fb2.zip"):
        filename = filename.removesuffix(".zip")

    return response.content, filename
