import toml
import pytest

from data.print_documents.place_cards import editor as editor_module
from data.print_documents.place_cards.editor import (
    PlaceCardTemplateEditor,
    PlaceCardTemplateEditorError,
)


@pytest.fixture
def custom_dir(tmp_path, monkeypatch):
    """Redirect the editor's custom templates directory to a temp folder."""
    target = tmp_path / 'place_cards'
    monkeypatch.setattr(editor_module, 'CUSTOM_PLACE_CARDS_DIR', target)
    # Undo/redo history is process-global; reset it so tests don't leak state.
    PlaceCardTemplateEditor._undo_history.clear()
    PlaceCardTemplateEditor._redo_history.clear()
    return target


def _read(custom_dir, template_id):
    folder, name = template_id.split('/')
    return toml.load(custom_dir / folder / f'{name}.template')


def test_create_writes_minimal_template_and_images_dir(custom_dir):
    template_id = PlaceCardTemplateEditor.create('club', 'board')
    # The folder/id is auto-derived (slugified) from the name.
    assert template_id == 'club/club'
    data = _read(custom_dir, template_id)
    assert data == {'type': 'board', 'name': 'club'}
    assert (custom_dir / 'club' / 'images').is_dir()


def test_create_stores_display_name_and_slugified_id(custom_dir):
    template_id = PlaceCardTemplateEditor.create('My Player Cards', 'player')
    assert template_id == 'My-Player-Cards/My-Player-Cards'
    assert _read(custom_dir, template_id)['name'] == 'My Player Cards'


def test_create_strips_accents_from_id(custom_dir):
    template_id = PlaceCardTemplateEditor.create('Numéro seulement', 'player')
    assert template_id == 'Numero-seulement/Numero-seulement'
    assert _read(custom_dir, template_id)['name'] == 'Numéro seulement'


def test_create_rejects_empty_name(custom_dir):
    with pytest.raises(PlaceCardTemplateEditorError):
        PlaceCardTemplateEditor.create('   ', 'player')


def test_create_twice_uses_distinct_folders(custom_dir):
    first = PlaceCardTemplateEditor.create('club', 'player')
    second = PlaceCardTemplateEditor.create('club', 'player')
    assert first != second


def test_read_metadata_defaults(custom_dir):
    template_id = PlaceCardTemplateEditor.create('club', 'player')
    values = PlaceCardTemplateEditor.read_metadata(template_id)
    assert values['type'] == 'player'
    assert values['name'] == 'club'
    assert values['width'] == 116.0
    assert values['bold'] is False
    assert values['h_align'] == 'left'


def test_save_persists_changes_and_drops_defaults(custom_dir):
    template_id = PlaceCardTemplateEditor.create('club', 'player')
    values = PlaceCardTemplateEditor.read_metadata(template_id)
    values['width'] = 200.0
    values['bold'] = True
    PlaceCardTemplateEditor.save_metadata(template_id, values)

    data = _read(custom_dir, template_id)
    assert data['width'] == 200.0
    assert data['bold'] is True
    # Unchanged defaults are not written to keep the file clean.
    assert 'padding' not in data
    assert 'height' not in data

    reread = PlaceCardTemplateEditor.read_metadata(template_id)
    assert reread['width'] == 200.0
    assert reread['bold'] is True


def test_save_removes_value_returned_to_default(custom_dir):
    template_id = PlaceCardTemplateEditor.create('club', 'player')
    values = PlaceCardTemplateEditor.read_metadata(template_id)
    values['width'] = 200.0
    PlaceCardTemplateEditor.save_metadata(template_id, values)
    assert 'width' in _read(custom_dir, template_id)

    values['width'] = 116.0
    PlaceCardTemplateEditor.save_metadata(template_id, values)
    assert 'width' not in _read(custom_dir, template_id)


def test_save_empty_name_is_dropped(custom_dir):
    template_id = PlaceCardTemplateEditor.create('club', 'player')
    values = PlaceCardTemplateEditor.read_metadata(template_id)
    values['name'] = ''
    PlaceCardTemplateEditor.save_metadata(template_id, values)
    assert 'name' not in _read(custom_dir, template_id)


def test_duplicate_embedded_creates_custom_copy(custom_dir):
    new_id = PlaceCardTemplateEditor.duplicate('player_01_standard')
    folder, name = new_id.split('/')
    assert name == 'player_01_standard'
    data = _read(custom_dir, new_id)
    # The copy gets a concrete display name (embedded name may be Jinja).
    assert data['name'] == 'player_01_standard'
    assert data['type'] == 'player'
    assert (custom_dir / folder / 'images').is_dir()


def test_duplicate_twice_uses_distinct_folders(custom_dir):
    first = PlaceCardTemplateEditor.duplicate('player_01_standard')
    second = PlaceCardTemplateEditor.duplicate('player_01_standard')
    assert first != second


def test_delete_removes_folder_when_last_template_gone(custom_dir):
    template_id = PlaceCardTemplateEditor.create('club', 'player')
    PlaceCardTemplateEditor.delete(template_id)
    assert not (custom_dir / 'club').exists()


def test_delete_keeps_folder_with_remaining_templates(custom_dir):
    template_id = PlaceCardTemplateEditor.create('club', 'player')
    # A folder may hold more than one .template (e.g. hand-authored); deleting
    # one must leave the folder (and the others) intact.
    (custom_dir / 'club' / 'extra.template').write_text('type = "board"\n')
    PlaceCardTemplateEditor.delete(template_id)
    assert (custom_dir / 'club').is_dir()
    assert (custom_dir / 'club' / 'extra.template').exists()


def test_delete_rejects_embedded(custom_dir):
    with pytest.raises(PlaceCardTemplateEditorError):
        PlaceCardTemplateEditor.delete('player_01_standard')


def test_save_rejects_embedded(custom_dir):
    with pytest.raises(PlaceCardTemplateEditorError):
        PlaceCardTemplateEditor.save_metadata('player_01_standard', {'type': 'player'})


# ----------------------------------------------------------------- item CRUD


def _new_template(custom_dir):
    return PlaceCardTemplateEditor.create('club', 'player')


def test_add_text_item_writes_only_set_values(custom_dir):
    template_id = _new_template(custom_dir)
    PlaceCardTemplateEditor.save_item(
        template_id,
        'player_name',
        'text',
        {'text': '{{ player.full_name }}', 'bold': 'yes', 'font_size': 18.0},
    )
    section = _read(custom_dir, template_id)['player_name']
    assert section == {
        'text': '{{ player.full_name }}',
        'bold': True,
        'font_size': 18.0,
    }


def test_add_image_item_allows_empty_filename(custom_dir):
    # An unchosen image is stored empty (renders as a placeholder box) but keeps
    # its image kind.
    template_id = _new_template(custom_dir)
    PlaceCardTemplateEditor.save_item(template_id, 'logo', 'image', {'image': ''})
    assert _read(custom_dir, template_id)['logo'] == {'image': ''}
    items = {
        item['id']: item for item in PlaceCardTemplateEditor.list_items(template_id)
    }
    assert items['logo']['kind'] == 'image'


def test_image_item_rejects_path_in_filename(custom_dir):
    template_id = _new_template(custom_dir)
    with pytest.raises(PlaceCardTemplateEditorError):
        PlaceCardTemplateEditor.save_item(
            template_id, 'logo', 'image', {'image': '../secret.png'}
        )


def test_list_items_reports_kind(custom_dir):
    template_id = _new_template(custom_dir)
    PlaceCardTemplateEditor.save_item(
        template_id, 'name', 'text', {'text': '{{ player.full_name }}'}
    )
    PlaceCardTemplateEditor.save_item(
        template_id, 'logo', 'image', {'image': 'logo.png'}
    )
    items = {
        item['id']: item for item in PlaceCardTemplateEditor.list_items(template_id)
    }
    assert items['name']['kind'] == 'text'
    assert items['logo']['kind'] == 'image'
    assert items['logo']['summary'] == 'logo.png'


def test_read_item_form_data_inherit_blanks(custom_dir):
    template_id = _new_template(custom_dir)
    PlaceCardTemplateEditor.save_item(
        template_id, 'name', 'text', {'text': 'x', 'bold': 'yes'}
    )
    form = PlaceCardTemplateEditor.read_item_form_data(template_id, 'name')
    assert form['bold'] == 'yes'
    assert form['italic'] == ''  # inherited -> blank
    assert form['font_size'] == ''  # inherited -> blank
    assert form['display'] == 'on'
    assert form['side'] == 'front'


def test_save_item_rename(custom_dir):
    template_id = _new_template(custom_dir)
    PlaceCardTemplateEditor.save_item(template_id, 'name', 'text', {'text': 'x'})
    PlaceCardTemplateEditor.save_item(
        template_id, 'renamed', 'text', {'text': 'x'}, original_section='name'
    )
    data = _read(custom_dir, template_id)
    assert 'name' not in data
    assert data['renamed']['text'] == 'x'


def test_save_item_rejects_duplicate_id(custom_dir):
    template_id = _new_template(custom_dir)
    PlaceCardTemplateEditor.save_item(template_id, 'name', 'text', {'text': 'x'})
    with pytest.raises(PlaceCardTemplateEditorError):
        PlaceCardTemplateEditor.save_item(template_id, 'name', 'text', {'text': 'y'})


def test_save_item_rejects_reserved_id(custom_dir):
    template_id = _new_template(custom_dir)
    with pytest.raises(PlaceCardTemplateEditorError):
        PlaceCardTemplateEditor.save_item(template_id, 'default', 'text', {'text': 'x'})


def test_save_item_editing_drops_cleared_values(custom_dir):
    template_id = _new_template(custom_dir)
    PlaceCardTemplateEditor.save_item(
        template_id, 'name', 'text', {'text': 'x', 'bold': 'yes'}
    )
    PlaceCardTemplateEditor.save_item(
        template_id, 'name', 'text', {'text': 'x', 'bold': ''}, original_section='name'
    )
    assert 'bold' not in _read(custom_dir, template_id)['name']


def test_delete_item(custom_dir):
    template_id = _new_template(custom_dir)
    PlaceCardTemplateEditor.save_item(template_id, 'name', 'text', {'text': 'x'})
    PlaceCardTemplateEditor.delete_item(template_id, 'name')
    assert 'name' not in _read(custom_dir, template_id)


def test_suggest_item_id_dedupes(custom_dir):
    template_id = _new_template(custom_dir)
    assert PlaceCardTemplateEditor.suggest_item_id(template_id, 'text') == 'text'
    PlaceCardTemplateEditor.save_item(template_id, 'text', 'text', {'text': 'x'})
    assert PlaceCardTemplateEditor.suggest_item_id(template_id, 'text') == 'text_2'


# ------------------------------------------------------- visual editor helpers


def test_add_default_text_item(custom_dir):
    template_id = _new_template(custom_dir)
    section = PlaceCardTemplateEditor.add_default_item(template_id, 'text')
    item = _read(custom_dir, template_id)[section]
    assert 'text' in item
    assert item['h_pos'] == 2.0 and item['v_pos'] == 2.0
    assert item['h_align'] == 'left' and item['v_align'] == 'top'


def test_add_default_image_item(custom_dir):
    template_id = _new_template(custom_dir)
    section = PlaceCardTemplateEditor.add_default_item(template_id, 'image')
    item = _read(custom_dir, template_id)[section]
    # A new image item starts with no image chosen (empty placeholder box).
    assert item['image'] == ''


def test_move_item_sets_edges_and_preserves_other_keys(custom_dir):
    template_id = _new_template(custom_dir)
    PlaceCardTemplateEditor.save_item(
        template_id, 'name', 'text', {'text': '{{ player.full_name }}', 'bold': 'yes'}
    )
    PlaceCardTemplateEditor.move_item(template_id, 'name', 'right', 'bottom', 12.5, 4.0)
    item = _read(custom_dir, template_id)['name']
    assert item['h_align'] == 'right' and item['v_align'] == 'bottom'
    assert item['h_pos'] == 12.5 and item['v_pos'] == 4.0
    # unrelated keys survive the move
    assert item['text'] == '{{ player.full_name }}'
    assert item['bold'] is True


def test_move_item_allows_negative_offset(custom_dir):
    # Negative offsets let an item overflow the card edge (clipped on render).
    template_id = _new_template(custom_dir)
    PlaceCardTemplateEditor.save_item(template_id, 'name', 'text', {'text': 'x'})
    PlaceCardTemplateEditor.move_item(template_id, 'name', 'left', 'top', -5.0, -1.0)
    item = _read(custom_dir, template_id)['name']
    assert item['h_pos'] == -5.0 and item['v_pos'] == -1.0


def test_move_item_changes_side(custom_dir):
    template_id = _new_template(custom_dir)
    PlaceCardTemplateEditor.save_item(template_id, 'name', 'text', {'text': 'x'})
    PlaceCardTemplateEditor.move_item(
        template_id, 'name', 'left', 'top', 1.0, 1.0, side='back'
    )
    assert _read(custom_dir, template_id)['name']['side'] == 'back'
    PlaceCardTemplateEditor.move_item(
        template_id, 'name', 'left', 'top', 1.0, 1.0, side='front'
    )
    assert 'side' not in _read(custom_dir, template_id)['name']


def test_move_item_rejects_bad_alignment(custom_dir):
    template_id = _new_template(custom_dir)
    PlaceCardTemplateEditor.save_item(template_id, 'name', 'text', {'text': 'x'})
    with pytest.raises(PlaceCardTemplateEditorError):
        PlaceCardTemplateEditor.move_item(
            template_id, 'name', 'sideways', 'top', 1.0, 1.0
        )


def test_add_default_item_with_field_token(custom_dir):
    template_id = _new_template(custom_dir)
    section = PlaceCardTemplateEditor.add_default_item(
        template_id, 'text', text='{{ player.rating }}'
    )
    assert _read(custom_dir, template_id)[section]['text'] == '{{ player.rating }}'


def test_patch_item_sets_and_deletes_preserving_position(custom_dir):
    template_id = _new_template(custom_dir)
    PlaceCardTemplateEditor.save_item(
        template_id,
        'name',
        'text',
        {'text': 'x', 'h_align': 'right', 'h_pos': 10.0, 'bold': 'yes'},
    )
    PlaceCardTemplateEditor.patch_item(
        template_id, 'name', {'color': '#ff0000', 'bold': None}
    )
    item = _read(custom_dir, template_id)['name']
    assert item['color'] == '#ff0000'
    assert 'bold' not in item
    assert item['h_align'] == 'right' and item['h_pos'] == 10.0
    assert item['text'] == 'x'


def test_patch_item_rejects_embedded(custom_dir):
    with pytest.raises(PlaceCardTemplateEditorError):
        PlaceCardTemplateEditor.patch_item(
            'player_01_standard', 'player_name', {'color': '#000'}
        )


def test_set_anchor_preserves_offsets(custom_dir):
    template_id = _new_template(custom_dir)
    PlaceCardTemplateEditor.save_item(
        template_id, 'name', 'text', {'text': 'x', 'h_pos': 8.0, 'v_pos': 3.0}
    )
    PlaceCardTemplateEditor.set_anchor(template_id, 'name', 'center', 'middle')
    item = _read(custom_dir, template_id)['name']
    assert item['h_align'] == 'center' and item['v_align'] == 'middle'
    assert item['h_pos'] == 8.0 and item['v_pos'] == 3.0


def test_set_anchor_rejects_bad_value(custom_dir):
    template_id = _new_template(custom_dir)
    PlaceCardTemplateEditor.save_item(template_id, 'name', 'text', {'text': 'x'})
    with pytest.raises(PlaceCardTemplateEditorError):
        PlaceCardTemplateEditor.set_anchor(template_id, 'name', 'somewhere', 'top')


def test_patch_metadata_merges_and_preserves_items(custom_dir):
    template_id = _new_template(custom_dir)
    PlaceCardTemplateEditor.save_item(template_id, 'name', 'text', {'text': 'x'})
    PlaceCardTemplateEditor.patch_metadata(
        template_id, {'width': 200.0, 'creator': None}
    )
    data = _read(custom_dir, template_id)
    assert data['width'] == 200.0
    # items are untouched by a metadata patch
    assert data['name']['text'] == 'x'


def test_export_zip_contains_template_and_images(custom_dir):
    import io
    import zipfile

    template_id = _new_template(custom_dir)
    PlaceCardTemplateEditor.save_item(template_id, 'name', 'text', {'text': 'x'})
    images_dir = custom_dir / template_id.split('/')[0] / 'images'
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / 'logo.png').write_bytes(b'PNG')

    filename, payload = PlaceCardTemplateEditor.export_zip(template_id)
    assert filename.endswith('.zip')
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
    assert any(n.endswith('.template') for n in names)
    assert 'images/logo.png' in names


def test_import_zip_round_trip(custom_dir, monkeypatch):
    # Skip the load-based validation (it reads the real template dirs).
    from data.print_documents.place_cards.template import PlaceCardTemplate

    monkeypatch.setattr(PlaceCardTemplate, 'load', staticmethod(lambda _id: None))

    template_id = _new_template(custom_dir)
    images_dir = custom_dir / template_id.split('/')[0] / 'images'
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / 'logo.png').write_bytes(b'PNG')
    _, payload = PlaceCardTemplateEditor.export_zip(template_id)

    zip_path = custom_dir.parent / 'export.zip'
    zip_path.write_bytes(payload)
    new_id = PlaceCardTemplateEditor.import_zip(zip_path, name='Imported')
    assert new_id == 'Imported/Imported'
    assert _read(custom_dir, new_id)['name'] == 'Imported'
    assert (custom_dir / 'Imported' / 'images' / 'logo.png').read_bytes() == b'PNG'


def test_import_zip_rejects_non_zip(custom_dir):
    bad = custom_dir.parent / 'not.zip'
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b'not a zip')
    with pytest.raises(PlaceCardTemplateEditorError):
        PlaceCardTemplateEditor.import_zip(bad)


def test_import_zip_rejects_multiple_templates(custom_dir):
    import zipfile

    zip_path = custom_dir.parent / 'multi.zip'
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'w') as archive:
        archive.writestr('a.template', 'type = "player"\n')
        archive.writestr('b.template', 'type = "player"\n')
    with pytest.raises(PlaceCardTemplateEditorError):
        PlaceCardTemplateEditor.import_zip(zip_path)


def test_undo_redo_round_trip(custom_dir):
    template_id = _new_template(custom_dir)
    # A fresh template has nothing to undo.
    assert PlaceCardTemplateEditor.can_undo(template_id) is False
    PlaceCardTemplateEditor.save_item(template_id, 'title', 'text', {'text': 'a'})
    PlaceCardTemplateEditor.patch_item(template_id, 'title', {'text': 'b'})
    assert _read(custom_dir, template_id)['title']['text'] == 'b'
    assert PlaceCardTemplateEditor.can_undo(template_id) is True

    assert PlaceCardTemplateEditor.undo(template_id) is True
    assert _read(custom_dir, template_id)['title']['text'] == 'a'
    assert PlaceCardTemplateEditor.can_redo(template_id) is True

    assert PlaceCardTemplateEditor.undo(template_id) is True  # undo the add
    assert 'title' not in _read(custom_dir, template_id)

    assert PlaceCardTemplateEditor.redo(template_id) is True
    assert _read(custom_dir, template_id)['title']['text'] == 'a'
    assert PlaceCardTemplateEditor.redo(template_id) is True
    assert _read(custom_dir, template_id)['title']['text'] == 'b'


def test_undo_empty_returns_false(custom_dir):
    template_id = _new_template(custom_dir)
    assert PlaceCardTemplateEditor.undo(template_id) is False
    assert PlaceCardTemplateEditor.redo(template_id) is False


def test_new_edit_clears_redo(custom_dir):
    template_id = _new_template(custom_dir)
    PlaceCardTemplateEditor.save_item(template_id, 'name', 'text', {'text': 'a'})
    PlaceCardTemplateEditor.undo(template_id)
    assert PlaceCardTemplateEditor.can_redo(template_id) is True
    # A fresh mutation invalidates the redo stack.
    PlaceCardTemplateEditor.save_item(template_id, 'other', 'text', {'text': 'x'})
    assert PlaceCardTemplateEditor.can_redo(template_id) is False
