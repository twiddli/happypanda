import queue, os, threading, random, logging, time, scandir
from datetime import datetime

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QDesktopWidget, QGroupBox,
                             QHBoxLayout, QFormLayout, QLabel, QLineEdit,
                             QPushButton, QProgressBar, QTextEdit, QComboBox,
                             QDateEdit, QFileDialog, QMessageBox, QScrollArea,
                             QCheckBox, QSizePolicy, QSpinBox, QDialog, QTabWidget,
                             QListView, QDialogButtonBox, QTableWidgetItem, QFrame)
from PyQt5.QtCore import (pyqtSignal, Qt, QPoint, QDate, QThread, QTimer, QSize)

import app_constants
import db_constants
import utils
import gallerydb
import fetch
import misc
import db

log = logging.getLogger(__name__)
log_i = log.info
log_d = log.debug
log_w = log.warning
log_e = log.error
log_c = log.critical

class GalleryDialog(QWidget):
    """
    A window for adding/modifying gallery.
    Pass a list of QModelIndexes to edit their data
    or pass a path to preset path
    """

    def __init__(self, parent, arg=None):
        super().__init__(parent, Qt.Dialog)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setAutoFillBackground(True)
        self.parent_widget = parent
        m_l = QVBoxLayout()
        self.main_layout = QVBoxLayout()
        dummy = QWidget(self)
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameStyle(scroll_area.StyledPanel)
        dummy.setLayout(self.main_layout)
        scroll_area.setWidget(dummy)
        m_l.addWidget(scroll_area, 3)

        final_buttons = QHBoxLayout()
        final_buttons.setAlignment(Qt.AlignRight)
        m_l.addLayout(final_buttons)
        self.done = QPushButton("Done")
        self.done.setDefault(True)
        cancel = QPushButton("Cancel")
        final_buttons.addWidget(cancel)
        final_buttons.addWidget(self.done)
        self._multiple_galleries = False
        self._edit_galleries = []

        def new_gallery():
            self.setWindowTitle('Add a new gallery')
            self.newUI()
            self.commonUI()
            self.done.clicked.connect(self.accept)
            cancel.clicked.connect(self.reject)

        if arg:
            if isinstance(arg, (list, gallerydb.Gallery)):
                if isinstance(arg, gallerydb.Gallery):
                    self.setWindowTitle('Edit gallery')
                    self._edit_galleries.append(arg)
                else:
                    self.setWindowTitle('Edit {} galleries'.format(len(arg)))
                    self._multiple_galleries = True
                    self._edit_galleries.extend(arg)
                self.commonUI()
                self.setGallery(arg)
                self.done.clicked.connect(self.accept_edit)
                cancel.clicked.connect(self.reject_edit)
            elif isinstance(arg, str):
                new_gallery()
                self.choose_dir(arg)
        else:
            new_gallery()

        log_d('GalleryDialog: Create UI: successful')
        self.setLayout(m_l)
        if self._multiple_galleries:
            self.resize(500, 400)
        else:
            self.resize(500, 600)
        frect = self.frameGeometry()
        frect.moveCenter(QDesktopWidget().availableGeometry().center())
        self.move(frect.topLeft())
        self._fetch_inst = fetch.Fetch()
        self._fetch_thread = QThread(self)
        self._fetch_thread.setObjectName("GalleryDialog metadata thread")
        self._fetch_inst.moveToThread(self._fetch_thread)
        self._fetch_thread.started.connect(self._fetch_inst.auto_web_metadata)

    def commonUI(self):
        if not self._multiple_galleries:
            f_web = QGroupBox("Metadata from the Web")
            f_web.setCheckable(False)
            self.main_layout.addWidget(f_web)
            web_main_layout = QVBoxLayout()
            web_info = misc.ClickedLabel("Which gallery URLs are supported? (hover)", parent=self)
            web_info.setToolTip(app_constants.SUPPORTED_METADATA_URLS)
            web_info.setToolTipDuration(999999999)
            web_main_layout.addWidget(web_info)
            web_layout = QHBoxLayout()
            web_main_layout.addLayout(web_layout)
            f_web.setLayout(web_main_layout)
            def basic_web(name):
                return QLabel(name), QLineEdit(), QPushButton("Get metadata"), QProgressBar()

            url_lbl, self.url_edit, url_btn, url_prog = basic_web("URL:")
            url_btn.clicked.connect(lambda: self.web_metadata(self.url_edit.text(), url_btn,
                                                url_prog))
            url_prog.setTextVisible(False)
            url_prog.setMinimum(0)
            url_prog.setMaximum(0)
            web_layout.addWidget(url_lbl, 0, Qt.AlignLeft)
            web_layout.addWidget(self.url_edit, 0)
            web_layout.addWidget(url_btn, 0, Qt.AlignRight)
            web_layout.addWidget(url_prog, 0, Qt.AlignRight)
            self.url_edit.setPlaceholderText("Insert supported gallery URLs or just press the button!")
            url_prog.hide()

        f_gallery = QGroupBox("Gallery Info")
        f_gallery.setCheckable(False)
        self.main_layout.addWidget(f_gallery)
        gallery_layout = QFormLayout()
        f_gallery.setLayout(gallery_layout)

        def checkbox_layout(widget):
            if self._multiple_galleries:
                l = QHBoxLayout()
                l.addWidget(widget.g_check)
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                l.addWidget(widget)
                return l
            else:
                widget.g_check.setChecked(True)
                widget.g_check.hide()
                return widget

        def add_check(widget):
            widget.g_check = QCheckBox(self)
            return widget

        self.title_edit = add_check(QLineEdit())
        self.author_edit = add_check(QLineEdit())
        author_completer = misc.GCompleter(self, False, True, False)
        author_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.author_edit.setCompleter(author_completer)
        self.descr_edit = add_check(QTextEdit())
        self.descr_edit.setAcceptRichText(True)
        self.lang_box = add_check(QComboBox())
        self.lang_box.addItems(app_constants.G_LANGUAGES)
        self.lang_box.addItems(app_constants.G_CUSTOM_LANGUAGES)
        self.rating_box = add_check(QSpinBox())
        self.rating_box.setMaximum(5)
        self.rating_box.setMinimum(0)
        self._find_combobox_match(self.lang_box, app_constants.G_DEF_LANGUAGE, 0)
        tags_l = QVBoxLayout()
        tag_info = misc.ClickedLabel("How do i write namespace & tags? (hover)", parent=self)
        tag_info.setToolTip("Ways to write tags:\n\nNormal tags:\ntag1, tag2, tag3\n\n"+
                      "Namespaced tags:\nns1:tag1, ns1:tag2\n\nNamespaced tags with one or more"+
                      " tags under same namespace:\nns1:[tag1, tag2, tag3], ns2:[tag1, tag2]\n\n"+
                      "Those three ways of writing namespace & tags can be combined freely.\n"+
                      "Tags are seperated by a comma, NOT whitespace.\nNamespaces will be capitalized while tags"+
                      " will be lowercased.")
        tag_info.setToolTipDuration(99999999)
        tags_l.addWidget(tag_info)
        self.tags_edit = add_check(misc.CompleterTextEdit())
        self.tags_edit.setCompleter(misc.GCompleter(self, False, False))
        if self._multiple_galleries:
            tags_l.addLayout(checkbox_layout(self.tags_edit), 3)
        else:
            tags_l.addWidget(checkbox_layout(self.tags_edit), 3)
        self.tags_edit.setPlaceholderText("Press Tab to autocomplete (Ctrl + E to show popup)")
        self.type_box = add_check(QComboBox())
        self.type_box.addItems(app_constants.G_TYPES)
        self._find_combobox_match(self.type_box, app_constants.G_DEF_TYPE, 0)
        #self.type_box.currentIndexChanged[int].connect(self.doujin_show)
        #self.doujin_parent = QLineEdit()
        #self.doujin_parent.setVisible(False)
        self.status_box = add_check(QComboBox())
        self.status_box.addItems(app_constants.G_STATUS)
        self._find_combobox_match(self.status_box, app_constants.G_DEF_STATUS, 0)
        self.pub_edit = add_check(QDateEdit())
        self.pub_edit.setCalendarPopup(True)
        self.pub_edit.setDate(QDate.currentDate())
        self.path_lbl = misc.ClickedLabel("")
        self.path_lbl.setWordWrap(True)
        self.path_lbl.clicked.connect(lambda a: utils.open_path(a, a) if a else None)

        link_layout = QHBoxLayout()
        self.link_lbl = add_check(QLabel(""))
        self.link_lbl.setWordWrap(True)
        self.link_edit = QLineEdit()
        link_layout.addWidget(self.link_edit)
        if self._multiple_galleries:
            link_layout.addLayout(checkbox_layout(self.link_lbl))
        else:
            link_layout.addWidget(checkbox_layout(self.link_lbl))
        self.link_edit.hide()
        self.link_btn = QPushButton("Modify")
        self.link_btn.setFixedWidth(50)
        self.link_btn2 = QPushButton("Set")
        self.link_btn2.setFixedWidth(40)
        self.link_btn.clicked.connect(self.link_modify)
        self.link_btn2.clicked.connect(self.link_set)
        link_layout.addWidget(self.link_btn)
        link_layout.addWidget(self.link_btn2)
        self.link_btn2.hide()
        
        rating_ = checkbox_layout(self.rating_box)
        lang_ = checkbox_layout(self.lang_box)
        if self._multiple_galleries:
            rating_.insertWidget(0, QLabel("Rating:"))
            lang_.addLayout(rating_)
            lang_l = lang_
        else:
            lang_l = QHBoxLayout()
            lang_l.addWidget(lang_)
            lang_l.addWidget(QLabel("Rating:"), 0, Qt.AlignRight)
            lang_l.addWidget(rating_)


        gallery_layout.addRow("Title:", checkbox_layout(self.title_edit))
        gallery_layout.addRow("Author:", checkbox_layout(self.author_edit))
        gallery_layout.addRow("Description:", checkbox_layout(self.descr_edit))
        gallery_layout.addRow("Language:", lang_l)
        gallery_layout.addRow("Tags:", tags_l)
        gallery_layout.addRow("Type:", checkbox_layout(self.type_box))
        gallery_layout.addRow("Status:", checkbox_layout(self.status_box))
        gallery_layout.addRow("Publication Date:", checkbox_layout(self.pub_edit))
        gallery_layout.addRow("Path:", self.path_lbl)
        gallery_layout.addRow("Link:", link_layout)

        self.title_edit.setFocus()

    def resizeEvent(self, event):
        self.tags_edit.setFixedHeight(event.size().height()//8)
        self.descr_edit.setFixedHeight(event.size().height()//12.5)
        return super().resizeEvent(event)

    def _find_combobox_match(self, combobox, key, default):
        f_index = combobox.findText(key, Qt.MatchFixedString)
        if f_index != -1:
            combobox.setCurrentIndex(f_index)
            return True
        else:
            combobox.setCurrentIndex(default)
            return False

    def setGallery(self, gallery):
        "To be used for when editing a gallery"
        if isinstance(gallery, gallerydb.Gallery):
            self.gallery = gallery

            if not self._multiple_galleries:
                self.url_edit.setText(gallery.link)

            self.title_edit.setText(gallery.title)
            self.author_edit.setText(gallery.artist)
            self.descr_edit.setText(gallery.info)
            self.rating_box.setValue(gallery.rating)

            self.tags_edit.setText(utils.tag_to_string(gallery.tags))


            if not self._find_combobox_match(self.lang_box, gallery.language, 1):
                self._find_combobox_match(self.lang_box, app_constants.G_DEF_LANGUAGE, 1)
            if not self._find_combobox_match(self.type_box, gallery.type, 0):
                self._find_combobox_match(self.type_box, app_constants.G_DEF_TYPE, 0)
            if not self._find_combobox_match(self.status_box, gallery.status, 0):
                self._find_combobox_match(self.status_box, app_constants.G_DEF_STATUS, 0)

            gallery_pub_date = "{}".format(gallery.pub_date).split(' ')
            try:
                self.gallery_time = datetime.strptime(gallery_pub_date[1], '%H:%M:%S').time()
            except IndexError:
                pass
            qdate_pub_date = QDate.fromString(gallery_pub_date[0], "yyyy-MM-dd")
            self.pub_edit.setDate(qdate_pub_date)

            self.link_lbl.setText(gallery.link)
            self.path_lbl.setText(gallery.path)

        elif isinstance(gallery, list):
            g = gallery[0]
            if all(map(lambda x: x.title == g.title, gallery)):
                self.title_edit.setText(g.title)
                self.title_edit.g_check.setChecked(True)
            if all(map(lambda x: x.artist == g.artist, gallery)):
                self.author_edit.setText(g.artist)
                self.author_edit.g_check.setChecked(True)
            if all(map(lambda x: x.info == g.info, gallery)):
                self.descr_edit.setText(g.info)
                self.descr_edit.g_check.setChecked(True)
            if all(map(lambda x: x.tags == g.tags, gallery)):
                self.tags_edit.setText(utils.tag_to_string(g.tags))
                self.tags_edit.g_check.setChecked(True)
            if all(map(lambda x: x.language == g.language, gallery)):
                if not self._find_combobox_match(self.lang_box, g.language, 1):
                    self._find_combobox_match(self.lang_box, app_constants.G_DEF_LANGUAGE, 1)
                self.lang_box.g_check.setChecked(True)
            if all(map(lambda x: x.rating == g.rating, gallery)):
                self.rating_box.setValue(g.rating)
                self.rating_box.g_check.setChecked(True)
            if all(map(lambda x: x.type == g.type, gallery)):
                if not self._find_combobox_match(self.type_box, g.type, 0):
                    self._find_combobox_match(self.type_box, app_constants.G_DEF_TYPE, 0)
                self.type_box.g_check.setChecked(True)
            if all(map(lambda x: x.status == g.status, gallery)):
                if not self._find_combobox_match(self.status_box, g.status, 0):
                    self._find_combobox_match(self.status_box, app_constants.G_DEF_STATUS, 0)
                self.status_box.g_check.setChecked(True)
            if all(map(lambda x: x.pub_date == g.pub_date, gallery)):
                gallery_pub_date = "{}".format(g.pub_date).split(' ')
                try:
                    self.gallery_time = datetime.strptime(gallery_pub_date[1], '%H:%M:%S').time()
                except IndexError:
                    pass
                qdate_pub_date = QDate.fromString(gallery_pub_date[0], "yyyy-MM-dd")
                self.pub_edit.setDate(qdate_pub_date)
                self.pub_edit.g_check.setChecked(True)
            if all(map(lambda x: x.link == g.link, gallery)):
                self.link_lbl.setText(g.link)
                self.link_lbl.g_check.setChecked(True)

    def newUI(self):

        f_local = QGroupBox("Directory/Archive")
        f_local.setCheckable(False)
        self.main_layout.addWidget(f_local)
        local_layout = QHBoxLayout()
        f_local.setLayout(local_layout)

        choose_folder = QPushButton("From Directory")
        choose_folder.clicked.connect(lambda: self.choose_dir('f'))
        local_layout.addWidget(choose_folder)

        choose_archive = QPushButton("From Archive")
        choose_archive.clicked.connect(lambda: self.choose_dir('a'))
        local_layout.addWidget(choose_archive)

        self.file_exists_lbl = QLabel()
        local_layout.addWidget(self.file_exists_lbl)
        self.file_exists_lbl.hide()

    def choose_dir(self, mode):
        """
        Pass which mode to open the folder explorer in:
        'f': directory
        'a': files
        Or pass a predefined path
        """
        self.done.show()
        self.file_exists_lbl.hide()
        if mode == 'a':
            name = QFileDialog.getOpenFileName(self, 'Choose archive',
                                              filter=utils.FILE_FILTER)
            name = name[0]
        elif mode == 'f':
            name = QFileDialog.getExistingDirectory(self, 'Choose folder')
        elif mode:
            if os.path.exists(mode):
                name = mode
            else:
                return None
        if not name:
            return
        head, tail = os.path.split(name)
        name = os.path.join(head, tail)
        parsed = utils.title_parser(tail)
        self.title_edit.setText(parsed['title'])
        self.author_edit.setText(parsed['artist'])
        self.path_lbl.setText(name)
        if not parsed['language']:
            parsed['language'] = app_constants.G_DEF_LANGUAGE
        l_i = self.lang_box.findText(parsed['language'])
        if l_i != -1:
            self.lang_box.setCurrentIndex(l_i)
        if gallerydb.GalleryDB.check_exists(name):
            self.file_exists_lbl.setText('<font color="red">Gallery already exists.</font>')
            self.file_exists_lbl.show()
        # check galleries
        gs = 1
        if name.endswith(utils.ARCHIVE_FILES):
            gs = len(utils.check_archive(name))
        elif os.path.isdir(name):
            g_dirs, g_archs = utils.recursive_gallery_check(name)
            gs = len(g_dirs) + len(g_archs)
        if gs == 0:
            self.file_exists_lbl.setText('<font color="red">Invalid gallery source.</font>')
            self.file_exists_lbl.show()
            self.done.hide()
        if app_constants.SUBFOLDER_AS_GALLERY:
            if gs > 1:
                self.file_exists_lbl.setText('<font color="red">More than one galleries detected in source! Use other methods to add.</font>')
                self.file_exists_lbl.show()
                self.done.hide()

    def check(self):
        if not self._multiple_galleries:
            if len(self.title_edit.text()) is 0:
                self.title_edit.setFocus()
                self.title_edit.setStyleSheet("border-style:outset;border-width:2px;border-color:red;")
                return False
            elif len(self.author_edit.text()) is 0:
                self.author_edit.setText("Unknown")

            if len(self.path_lbl.text()) == 0 or self.path_lbl.text() == 'No path specified':
                self.path_lbl.setStyleSheet("color:red")
                self.path_lbl.setText('No path specified')
                return False

        return True

    def reject(self):
        if self.check():
            msgbox = QMessageBox()
            msgbox.setText("<font color='red'><b>Noo oniichan! You were about to add a new gallery.</b></font>")
            msgbox.setInformativeText("Do you really want to discard?")
            msgbox.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msgbox.setDefaultButton(QMessageBox.No)
            if msgbox.exec() == QMessageBox.Yes:
                self.close()
        else:
            self.close()

    def web_metadata(self, url, btn_widget, pgr_widget):
        if not self.path_lbl.text():
            return
        self.link_lbl.setText(url)
        btn_widget.hide()
        pgr_widget.show()

        def status(stat):
            def do_hide():
                try:
                    pgr_widget.hide()
                    btn_widget.show()
                except RuntimeError:
                    pass

            if stat:
                do_hide()
            else:
                danger = """QProgressBar::chunk {
                    background: QLinearGradient( x1: 0, y1: 0, x2: 1, y2: 0,stop: 0 #FF0350,stop: 0.4999 #FF0020,stop: 0.5 #FF0019,stop: 1 #FF0000 );
                    border-bottom-right-radius: 5px;
                    border-bottom-left-radius: 5px;
                    border: .px solid black;}"""
                pgr_widget.setStyleSheet(danger)
                QTimer.singleShot(3000, do_hide)

        def gallery_picker(gallery, title_url_list, q):
            self.parent_widget._web_metadata_picker(gallery, title_url_list, q, self)

        try:
            dummy_gallery = self.make_gallery(self.gallery, False)
        except AttributeError:
            dummy_gallery = self.make_gallery(gallerydb.Gallery(), False, True)
        if not dummy_gallery:
            status(False)
            return None

        dummy_gallery._g_dialog_url = url
        self._fetch_inst.galleries = [dummy_gallery]
        self._disconnect()
        self._fetch_inst.GALLERY_PICKER.connect(gallery_picker)
        self._fetch_inst.GALLERY_EMITTER.connect(self.set_web_metadata)
        self._fetch_inst.FINISHED.connect(status)
        self._fetch_thread.start()
            
    def set_web_metadata(self, metadata):
        assert isinstance(metadata, gallerydb.Gallery)
        self.link_lbl.setText(metadata.link)
        self.title_edit.setText(metadata.title)
        self.author_edit.setText(metadata.artist)
        tags = ""
        lang = ['English', 'Japanese']
        self._find_combobox_match(self.lang_box, metadata.language, 2)
        self.tags_edit.setText(utils.tag_to_string(metadata.tags))
        pub_string = "{}".format(metadata.pub_date)
        pub_date = QDate.fromString(pub_string.split()[0], "yyyy-MM-dd")
        self.pub_edit.setDate(pub_date)
        self._find_combobox_match(self.type_box, metadata.type, 0)

    def make_gallery(self, new_gallery, add_to_model=True, new=False):
        def is_checked(widget):
            return widget.g_check.isChecked()
        if self.check():
            if is_checked(self.title_edit):
                new_gallery.title = self.title_edit.text()
                log_d('Adding gallery title')
            if is_checked(self.author_edit):
                new_gallery.artist = self.author_edit.text()
                log_d('Adding gallery artist')
            if not self._multiple_galleries:
                new_gallery.path = self.path_lbl.text()
                log_d('Adding gallery path')
            if is_checked(self.descr_edit):
                new_gallery.info = self.descr_edit.toPlainText()
                log_d('Adding gallery descr')
            if is_checked(self.type_box):
                new_gallery.type = self.type_box.currentText()
                log_d('Adding gallery type')
            if is_checked(self.lang_box):
                new_gallery.language = self.lang_box.currentText()
                log_d('Adding gallery lang')
            if is_checked(self.rating_box):
                new_gallery.rating = self.rating_box.value()
                log_d('Adding gallery rating')
            if is_checked(self.status_box):
                new_gallery.status = self.status_box.currentText()
                log_d('Adding gallery status')
            if is_checked(self.tags_edit):
                new_gallery.tags = utils.tag_to_dict(self.tags_edit.toPlainText())
                log_d('Adding gallery: tagging to dict')
            if is_checked(self.pub_edit):
                qpub_d = self.pub_edit.date().toString("ddMMyyyy")
                dpub_d = datetime.strptime(qpub_d, "%d%m%Y").date()
                try:
                    d_t = self.gallery_time
                except AttributeError:
                    d_t = datetime.now().time().replace(microsecond=0)
                dpub_d = datetime.combine(dpub_d, d_t)
                new_gallery.pub_date = dpub_d
                log_d('Adding gallery pub date')
            if is_checked(self.link_lbl):
                new_gallery.link = self.link_lbl.text()
                log_d('Adding gallery link')

            if new:
                if not new_gallery.chapters:
                    log_d('Starting chapters')
                    thread = threading.Thread(target=utils.make_chapters, args=(new_gallery,))
                    thread.start()
                    thread.join()
                    log_d('Finished chapters')
                    if new and app_constants.MOVE_IMPORTED_GALLERIES:
                        app_constants.OVERRIDE_MONITOR = True
                        new_gallery.move_gallery()
                if add_to_model:
                    self.parent_widget.default_manga_view.add_gallery(new_gallery, True)
                    log_i('Sent gallery to model')
            else:
                if add_to_model:
                    self.parent_widget.default_manga_view.replace_gallery([new_gallery], False)
            return new_gallery


    def link_set(self):
        t = self.link_edit.text()
        self.link_edit.hide()
        self.link_lbl.show()
        self.link_lbl.setText(t)
        self.link_btn2.hide()
        self.link_btn.show() 

    def link_modify(self):
        t = self.link_lbl.text()
        self.link_lbl.hide()
        self.link_edit.show()
        self.link_edit.setText(t)
        self.link_btn.hide()
        self.link_btn2.show()

    def _disconnect(self):
        try:
            self._fetch_inst.GALLERY_PICKER.disconnect()
            self._fetch_inst.GALLERY_EMITTER.disconnect()
            self._fetch_inst.FINISHED.disconnect()
        except TypeError:
            pass

    def delayed_close(self):
        if self._fetch_thread.isRunning():
            self._fetch_thread.finished.connect(self.close)
            self.hide()
        else:
            self.close()

    def accept(self):
        self.make_gallery(gallerydb.Gallery(), new=True)
        self.delayed_close()

    def accept_edit(self):
        gallerydb.execute(database.db.DBBase.begin, True)
        for g in self._edit_galleries:
            self.make_gallery(g)
        self.delayed_close()
        gallerydb.execute(database.db.DBBase.end, True)

    def reject_edit(self):
        self.delayed_close()

class Item:
    def __init__(self, gallery):
        assert isinstance(gallery, db.Gallery)
        self.title = QTableWidgetItem(gallery.title)

class ItemList(misc.DefaultTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(3)
        self.setIconSize(QSize(50, 100))
        self.setHorizontalHeaderLabels(
	        [' ', 'Title', 'Status'])
        self.horizontalHeader().setSectionResizeMode(1, self.horizontalHeader().Stretch)
        self.horizontalHeader().setSectionResizeMode(1, self.horizontalHeader().ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(2, self.horizontalHeader().ResizeToContents)

    def add_item(self, item):
        assert isinstance(item, Item)
        self.insertRow(self.rowCount()+1)
        row = self.rowCount()-1
        self.setItem(row, 1, item.title)

class ItemsBase(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

    def items(self):
        return

class GalleryAddItems(ItemsBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        thread = QThread(self)
        self.scan = fetch.GalleryScan()
        self.scan.moveToThread(thread)
        self.scan.galleryitem.connect(self.add_scanitem)
        self.session = db_constants.SESSION()

        main_layout = QVBoxLayout(self)
        
        add_box = QGroupBox("Add Gallery", self)
        main_layout.addWidget(add_box)
        add_box_main_l = QVBoxLayout(add_box)
        add_box_l = QHBoxLayout()
        add_box_main_l.addLayout(add_box_l)
        add_box_l.setAlignment(Qt.AlignLeft)
        add_gallery_group = QGroupBox(self)
        add_gallery_l = QHBoxLayout(add_gallery_group)
        from_folder = QPushButton(app_constants.PLUS_ICON, "Add folder")
        from_folder.clicked.connect(lambda: self.file_or_folder('f'))
        from_archive = QPushButton(app_constants.PLUS_ICON, "Add archive")
        from_archive.clicked.connect(lambda: self.file_or_folder('a'))
        misc.fixed_widget_size(from_archive)
        misc.fixed_widget_size(from_folder)
        add_gallery_l.addWidget(from_archive)
        add_gallery_l.addWidget(from_folder)
        populate_group = QGroupBox(self)
        populate_group_l = QHBoxLayout(populate_group)
        populate_folder = QPushButton(app_constants.PLUS_ICON, "Populate from folder")
        misc.fixed_widget_size(populate_folder)
        populate_group_l.addWidget(populate_folder)
        self.same_namespace = QCheckBox("Put folders and/or archives in same namespace", self)
        self.skip_existing = QCheckBox("Skip already existing galleries", self)
        populate_group_l.addWidget(self.same_namespace)
        add_box_l.addWidget(add_gallery_group)
        add_box_l.addWidget(populate_group)
        add_box_main_l.addWidget(self.skip_existing)

        self.item_list = ItemList(self)
        self.item_list.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        main_layout.addWidget(self.item_list, 2)

    def file_or_folder(self, mode):
        """
        Pass which mode to open the folder explorer in:
        'f': directory
        'a': files
        Or pass a predefined path
        """
        if mode == 'a':
            name = QFileDialog.getOpenFileName(self, 'Choose archive',
                                              filter=utils.FILE_FILTER)
            name = name[0]
        elif mode == 'f':
            name = QFileDialog.getExistingDirectory(self, 'Choose folder')
        elif mode:
            if os.path.exists(mode):
                name = mode
            else:
                return None
        if name:
            pass
        self.scan.from_path_s.emit(name, tuple())

    def add_scanitem(self, item):
        assert isinstance(item, fetch.GalleryScanItem)
        self.session.add(item.gallery)
        self.session.commit()
        print(item.gallery)
       

class GalleryMetadataWidget(QWidget):
    up = pyqtSignal(object)
    down = pyqtSignal(object)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContentsMargins(0,0,0,0)
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        self.checkbox = QCheckBox()
        self.label = QLabel("E-Hentai")
        self.label.setAlignment(Qt.AlignLeft)
        up_btn = QPushButton(app_constants.ARROW_UP_ICON, '')
        misc.fixed_widget_size(up_btn)
        up_btn.clicked.connect(self.up.emit)
        down_btn = QPushButton(app_constants.ARROW_DOWN_ICON, '')
        down_btn.clicked.connect(self.down.emit)
        misc.fixed_widget_size(down_btn)
        h_l = QHBoxLayout()
        h_l.setSpacing(0)
        h_l.addWidget(self.checkbox)
        h_l.addWidget(self.label, 0, Qt.AlignLeft)
        h_l.addWidget(up_btn)
        h_l.addWidget(down_btn)
        main_layout.addLayout(h_l)
        main_layout.addWidget(misc.Line("h"))

class GalleryMetadataItems(ItemsBase):
    def __init__(self, parent=None):
        super().__init__(parent)

        main_layout = QVBoxLayout(self)
        
        settings_l = QVBoxLayout()
        settings_l.setSpacing(0)

        metadata_group = QGroupBox("Metadata Providers", self)
        metadata_group_l = QVBoxLayout(metadata_group)
        metadata_group_l.setSpacing(0)
        for x in range(3):
            metadata_group_l.addWidget(GalleryMetadataWidget(self))
        settings_l.addWidget(metadata_group)

        settings_btn_l = QHBoxLayout()
        settings_btn_l.setAlignment(Qt.AlignRight)
        settings_l.addLayout(settings_btn_l)
        main_layout.addLayout(settings_l)
        fetch_btn = QPushButton("Fetch")
        misc.fixed_widget_size(fetch_btn)
        self.auto_fetch = QCheckBox("Start fetching automatically", self)
        settings_btn_l.addWidget(self.auto_fetch, 0, Qt.AlignLeft)
        settings_btn_l.addWidget(fetch_btn, 0, Qt.AlignRight)

        self.item_list = ItemList(self)
        self.item_list.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        main_layout.addWidget(self.item_list, 2)

class GalleryTypeWidget(QFrame):
    remove = pyqtSignal(object)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(self.StyledPanel)
        main_layout = QFormLayout(self)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Name")
        self.color = QLineEdit()
        self.color.setPlaceholderText("Color")
        main_layout.addRow(self.name, self.color)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, ev):
        if ev.button() & Qt.LeftButton:
            self.remove.emit(self)
        return super().mousePressEvent(ev)

class MiscItems(ItemsBase):
    def __init__(self, parent=None):
        super().__init__(parent)

        main_layout = QVBoxLayout(self)
        
        add_collection = QGroupBox("Add Collection", self)
        main_layout.addWidget(add_collection)
        add_collection_l = QFormLayout(add_collection)
        add_collection_l.setAlignment(Qt.AlignLeft)
        self.collection_name = QLineEdit(self)
        self.collection_name.setPlaceholderText("New collection name...")
        self.collection_cover = misc.PathLineEdit(self)
        self.collection_info = QTextEdit(self)
        self.collection_info.setAcceptRichText(True)
        new_collection = QPushButton(app_constants.PLUS_ICON, "New Collection")
        misc.fixed_widget_size(new_collection)
        add_collection_l.addRow("Name:", self.collection_name)
        add_collection_l.addRow("Cover:", self.collection_cover)
        add_collection_l.addRow("Description:", self.collection_info)
        add_collection_l.addRow(new_collection)

        add_gtype = QGroupBox("Gallery Type", self)
        main_layout.addWidget(add_gtype)
        add_gtype_l = QVBoxLayout(add_gtype)
        self.new_gtype = QPushButton(app_constants.PLUS_ICON, "New Gallery Type")
        misc.fixed_widget_size(self.new_gtype)
        self.new_gtype.clicked.connect(self.add_gtype)
        add_gtype_l.addWidget(self.new_gtype)
        self.gtypes = misc.FlowLayout()
        add_gtype_l.addLayout(self.gtypes)

        add_language = QGroupBox("Language", self)
        main_layout.addWidget(add_language)
        add_language_l = QVBoxLayout(add_language)
        self.new_language = QLineEdit(self)
        self.new_language.returnPressed.connect(self.add_language)
        self.new_language.setPlaceholderText("New language (Click to remove)")
        add_language_l.addWidget(self.new_language)
        self.languages = misc.FlowLayout()
        add_language_l.addLayout(self.languages)

        add_status = QGroupBox("Status", self)
        main_layout.addWidget(add_status)
        add_status_l = QVBoxLayout(add_status)
        self.new_status = QLineEdit(self)
        self.new_status.returnPressed.connect(self.add_status)
        self.new_status.setPlaceholderText("New status (Click to remove)")
        add_status_l.addWidget(self.new_status)
        self.status = misc.FlowLayout()
        add_status_l.addLayout(self.status)

    def add_gtype(self):
        gtype = GalleryTypeWidget(self)
        gtype.remove.connect(self.remove_gtype)
        self.gtypes.addWidget(gtype)

    def remove_gtype(self, widget):
        self.gtypes.removeWidget(widget)
        widget.setParent(None)

    def add_language(self):
        lang = self.new_language.text()
        self.new_language.clear()
        lang_btn = misc.TagText(lang)
        lang_btn.clicked.connect(lambda: self.remove_language(lang_btn))
        self.languages.addWidget(lang_btn)

    def remove_language(self, widget):
        self.languages.removeWidget(widget)
        widget.setParent(None)

    def add_status(self):
        status = self.new_status.text()
        self.new_status.clear()
        status_btn = misc.TagText(status)
        status_btn.clicked.connect(lambda: self.remove_language(status_btn))
        self.status.addWidget(status_btn)

    def remove_status(self, widget):
        self.status.removeWidget(widget)
        widget.setParent(None)


class ItemManager(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Dialog)
        main_layout = QVBoxLayout(self)

        self.tabwidget = QTabWidget(self)
        self.tabwidget.addTab(GalleryAddItems(), "&Gallery")
        self.tabwidget.addTab(MiscItems(), "&Misc")

        buttonbox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Close)
        buttonbox.accepted.connect(self.accept)
        buttonbox.rejected.connect(self.close)

        main_layout.addWidget(self.tabwidget)
        main_layout.addWidget(buttonbox)
        self.setWindowTitle("Addition Manager")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(700, 700)
        self.show()
        
    def accept(self):
        pass


class MetadataManager(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Dialog)
        main_layout = QVBoxLayout(self)

        self.tabwidget = QTabWidget(self)
        self.tabwidget.addTab(GalleryMetadataItems(), "&Queue")

        main_layout.addWidget(self.tabwidget)
        self.setWindowTitle("Metadata Manager")
        self.resize(700, 700)

    def closeEvent(self, event):
        self.hide()