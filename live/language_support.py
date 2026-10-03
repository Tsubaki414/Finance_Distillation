"""Explicit language capabilities. The shipped detector supports EN/ZH only.

Adding a language needs a detector/QA validation, not a new pipeline. A label in
an account file alone never claims that an untested language is supported.
"""
from dataclasses import dataclass
from typing import Callable
import re


def detect_en_zh(text):
    han=len(re.findall(r'[\u4e00-\u9fff]',text));latin=len(re.findall(r'[A-Za-z]',text))
    if han>=8 and han/max(han+latin,1)>.18:return 'zh',.95
    words=re.findall(r'\b(?:the|a|an|is|are|was|were|of|to|in|and|if|that|with|from|for|our|but|has)\b',text,re.I)
    if han==0 and len(words)>=3:return 'en',.9
    return 'unknown',0.0


@dataclass(frozen=True)
class LanguageSupport:
    codes:frozenset[str]
    detect:Callable
    version:str


DEFAULT=LanguageSupport(frozenset({'en','zh'}),detect_en_zh,'en-zh-heuristic-v1')
