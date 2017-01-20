"""LineEdit for color input."""
import sys
import logging

from PyQt5 import QtWidgets
from PyQt5.QtWidgets import (
    QLineEdit,
    QHBoxLayout,
    QPushButton,
    QWidget,
    QColorDialog
)
from PyQt5.QtGui import (
    QColor,
    QRegularExpressionValidator,
)
from PyQt5.QtCore import (
    QRegularExpression,
)
log = logging.getLogger(__name__)
log_d = log.debug


class ColorLineEdit(QLineEdit):
    """custom line edit for color input.

    Hex color regex taken from:
        mkyong.com/regular-expressions/how-to-validate-hex-color-code-with-regular-expression/

    Args:
        hex_color (str): Default hex color.

    Attributes:
        default_color (str): Default color.
        button (QPushButton): Button which reflect the input from user.
        color_dialog (QColorDialog): Color dialog for this widget.
    """

    hexcolor_regex = r'^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$'
    button_stylesheet_format = \
        'background-color: {}; border: 1px solid black; border-radius: 5px;'

    def __init__(self, parent=None, hex_color=None):
        """init method."""
        super(ColorLineEdit, self).__init__(parent)
        self.init_ui(hex_color=hex_color)

    def init_ui(self, hex_color=None):
        """."""
        self.setMaxLength(7)
        self.setPlaceholderText('Hex colors. Eg.: #323232')
        self.setMaximumWidth(200)
        # attr
        self.default_color = hex_color if hex_color is not None else '#fff'

        self.button = QPushButton()
        self.button.setMaximumWidth(200)
        self.button.setStyleSheet(self.button_stylesheet_format.format(self.default_color))
        self.color_dialog = QColorDialog()
        self.button.clicked.connect(self.button_click)

        regex = QRegularExpression(self.hexcolor_regex)
        validator = QRegularExpressionValidator(regex, parent=self.validator())
        self.setValidator(validator)

        self.editingFinished.connect(self.update_button_color)

    def button_click(self):
        """Function to run when button clicked.

        Get the text from input, and use it as default arg for color selection dialog.
        If dialog return valid result, update the button and text input.
        """
        color_number = self.text()
        current_color = QColor(color_number)
        color_from_dialog = self.color_dialog.getColor(current_color)
        if color_from_dialog.isValid():
            color_name = color_from_dialog.name()
            self.button.setStyleSheet(self.button_stylesheet_format.format(color_name))
            self.setText(color_name)
        else:
            log_d('color is not valid')

    def update_button_color(self):
        """Update button's color."""
        color_text = self.text()
        self.button.setStyleSheet(self.button_stylesheet_format.format(color_text))


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    hbox_layout = QHBoxLayout()
    line_edit = ColorLineEdit()
    hbox_layout.addWidget(line_edit)
    hbox_layout.addWidget(line_edit.button)

    window = QWidget()
    window.setLayout(hbox_layout)
    window.show()

    sys.exit(app.exec_())
