from pathlib import Path
import os
import re
from datetime import datetime
import random
from typing import Optional

from whoosh.index import create_in, exists_in, open_dir
from whoosh.fields import Schema, TEXT, ID, STORED, DATETIME
from whoosh.qparser import QueryParser
from whoosh.writing import IndexWriter
from whoosh.query import Term, And, Or
import whoosh.highlight as highlight
from jieba.analyse.analyzer import ChineseAnalyzer


class Message:
    # TODO: add sender to Message schema
    schema = Schema(
        content=TEXT(stored=True, analyzer=ChineseAnalyzer()),
        url=ID(stored=True, unique=True),
        chat_id=STORED(),
        post_time=DATETIME(stored=True, sortable=True),
    )

    def __init__(self, content: str, url: str, chat_id: int, post_time: datetime):
        self.content = content
        self.url = url
        self.chat_id = chat_id
        self.post_time = post_time

    def as_dict(self):
        return {
            'content': self.content,
            'url': self.url,
            'chat_id': self.chat_id,
            'post_time': self.post_time,
        }


class SearchHit:
    def __init__(self, msg: Message, highlighted: str):
        self.msg = msg
        self.highlighted = highlighted


class SearchResult:
    def __init__(self, hits: list[SearchHit], is_last_page: bool, total_results: int):
        self.hits = hits
        self.is_last_page = is_last_page
        self.total_results = total_results


class Indexer:
    # A wrapper of whoosh

    def __init__(self, index_dir: Path, index_name: str, from_scratch: bool = False):
        if not Path(index_dir).exists():
            Path(index_dir).mkdir()

        def _clear():
            import shutil
            shutil.rmtree(index_dir)
            index_dir.mkdir()
            self.ix = create_in(index_dir, Message.schema, index_name)

        if from_scratch:
            _clear()

        self.ix = open_dir(index_dir, index_name) \
            if exists_in(index_dir, index_name) \
            else create_in(index_dir, Message.schema, index_name)

        self._clear = _clear  # use closure to avoid introducing too much members
        self.query_parser = QueryParser('content', Message.schema)
        self.highlighter = highlight.Highlighter()

    def retrieve_random_document(self) -> Message:
        with self.ix.searcher() as searcher:
            msg_dict = random.choice(list(searcher.documents()))
            return Message(**msg_dict)

    def add_document(self, message: Message, writer: Optional[IndexWriter] = None):
        if writer is not None:
            writer.add_document(**message.as_dict())
        else:
            with self.ix.writer() as writer:
                writer.add_document(**message.as_dict())

    def search(self, q_str: str, in_chats: Optional[list[int]], page_len: int, page_num: int = 1) -> SearchResult:
        q = self.query_parser.parse(q_str)
        with self.ix.searcher() as searcher:
            if in_chats:
                q = And(q, Or(*[Term('chat_id', chat_id) for chat_id in in_chats]))
            result_page = searcher.search_page(q, page_num, page_len,
                                               sortedby='post_time', reverse=True)

            hits = [SearchHit(Message(**msg), self.highlighter.highlight_hit(msg, 'content'))
                    for msg in result_page]
            return SearchResult(hits, result_page.is_last_page(), result_page.total)

    def delete(self, url: str):
        with self.ix.writer() as writer:
            writer.delete_by_term('url', url)

    def update(self, content: str, url: str):
        with self.ix.searcher() as searcher:
            msg_dict = searcher.document(url=url)
        with self.ix.writer() as writer:
            msg_dict['content'] = content
            writer.update_document(**msg_dict)

    def clear(self):
        self._clear()
