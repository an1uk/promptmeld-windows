from promptmeld.theme import (
    high_contrast_stylesheet,
    message_box_stylesheet,
    system_high_contrast_enabled,
    system_reduced_motion_enabled,
)


def test_windows_accessibility_preferences_are_safe_boolean_queries():
    assert isinstance(system_high_contrast_enabled(), bool)
    assert isinstance(system_reduced_motion_enabled(), bool)


def test_high_contrast_stylesheet_uses_system_palette_roles():
    stylesheet = high_contrast_stylesheet()

    assert "palette(window-text)" in stylesheet
    assert "palette(base)" in stylesheet
    assert "palette(highlight)" in stylesheet


def test_message_box_styles_are_complete_and_scoped_in_both_themes():
    for theme, foreground, background in (
        ("light", "#111827", "#ffffff"),
        ("dark", "#ffffff", "#17191e"),
    ):
        stylesheet = message_box_stylesheet(theme)

        assert "QMessageBox QLabel#qt_msgbox_label" in stylesheet
        assert foreground in stylesheet
        assert background in stylesheet
        assert "QMessageBox QPushButton" in stylesheet
        assert "QMessageBox QTextEdit" in stylesheet
        assert "QDialog" not in stylesheet
