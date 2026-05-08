from __future__ import annotations

from jamarr_tui.widgets.art_panel import ArtPanel


def test_art_panel_deletes_kitty_placement_when_hidden(monkeypatch) -> None:
    deleted: list[int] = []
    monkeypatch.setattr(
        "jamarr_tui.widgets.art_panel.kitty.delete_placement",
        lambda image_id: deleted.append(image_id),
    )

    panel = ArtPanel(client=object())  # type: ignore[arg-type]
    panel._kitty = True  # noqa: SLF001
    panel._kitty_uploaded = True  # noqa: SLF001
    panel._image_id = 1234  # noqa: SLF001

    panel.on_hide(None)  # type: ignore[arg-type]

    assert deleted == [1234]
    assert panel._visible is False  # noqa: SLF001


def test_hidden_art_panel_does_not_place_kitty_image(monkeypatch) -> None:
    placed: list[int] = []
    monkeypatch.setattr(
        "jamarr_tui.widgets.art_panel.kitty.place",
        lambda image_id, *args: placed.append(image_id),
    )

    panel = ArtPanel(client=object())  # type: ignore[arg-type]
    panel._kitty = True  # noqa: SLF001
    panel._kitty_uploaded = True  # noqa: SLF001
    panel._kitty_dims = (600, 600)  # noqa: SLF001
    panel._visible = False  # noqa: SLF001

    assert panel.render().plain == " "
    assert placed == []
