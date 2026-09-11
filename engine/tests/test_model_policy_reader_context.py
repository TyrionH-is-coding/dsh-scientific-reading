import hashlib

import pytest
from bs4 import BeautifulSoup

from scientific_reading import model_policy
from scientific_reading.library_service import LibraryService
from scientific_reading.reader_context import context
from test_reader_appearance import ready


def test_policy_defaults_save_reload_and_stale_write(tmp_path):
    library = LibraryService(tmp_path)
    initial = model_policy.read(library)
    assert len(initial['steps']) == 11
    assert {row['reasoningEffort'] for row in initial['steps'].values()} == {'medium'}
    assert initial['steps']['full_translation']['model'] == 'gpt-5.6-luna'
    assert initial['steps']['full_review']['model'] == 'gpt-5.6-sol'
    payload = {'revision': 0, 'steps': {'full_translation': {'provider': 'test', 'model': 'custom', 'reasoningEffort': 'low'}}}
    assert model_policy.save(library, payload)['revision'] == 1
    with pytest.raises(ValueError, match='model_policy_changed'):
        model_policy.save(library, payload)
    library.close()
    reopened = LibraryService(tmp_path)
    assert model_policy.read(reopened)['steps']['full_translation']['model'] == 'custom'
    assert model_policy.read(reopened)['steps']['full_review'] == initial['steps']['full_review']
    reopened.close()


def test_reader_context_verifies_quote_and_generation_without_changing_source(tmp_path):
    library, paper, generation, path = ready(tmp_path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    soup = BeautifulSoup(path.read_text(encoding='utf-8'), 'html.parser')
    block = soup.select_one('.reading-block:has(.source-primary):has(.translation-panel)')
    quote = ' '.join(block.select_one('.translation-panel').get_text(' ', strip=True).split())
    payload = {'paper_id': paper, 'source_pdf_sha256': soup.body['data-source-pdf-sha256'],
               'selection': {'block_ids': [block['data-block']], 'quote': quote}, 'question': '解释这句话'}
    result = context(library, payload)
    assert result['quote'] == quote
    assert any(row['block_id'] == block['data-block'] and row['source_en'] for row in result['passages'])
    assert result['reader_sha256'] == before
    with pytest.raises(ValueError, match='reader_selection_changed'):
        context(library, payload | {'selection': {'block_ids': [block['data-block']], 'quote': '伪造的论文内容'}})
    with pytest.raises(ValueError, match='reader_source_changed'):
        context(library, payload | {'source_pdf_sha256': 'a' * 64})
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    library.close()
