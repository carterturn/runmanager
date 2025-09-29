from qtutils.qt import QtCore, QtGui, QtWidgets

class FingerTabBarWidget(QtWidgets.QTabBar):

    """A TabBar with the tabs on the left and the text horizontal. Credit to
    @LegoStormtroopr, https://gist.github.com/LegoStormtroopr/5075267. We will
    promote the TabBar from the ui file to one of these."""

    def __init__(self, parent=None, minwidth=180, minheight=30, **kwargs):
        QtWidgets.QTabBar.__init__(self, parent, **kwargs)
        self.minwidth = minwidth
        self.minheight = minheight
        self.iconPosition = kwargs.pop('iconPosition', QtWidgets.QTabWidget.West)
        self._movable = None
        self.tab_movable = {}
        self.paint_clip = None

    def setMovable(self, movable, index=None):
        """Set tabs movable on an individual basis, or set for all tabs if no
        index specified"""
        if index is None:
            self._movable = movable
            self.tab_movable = {}
            QtWidgets.QTabBar.setMovable(self, movable)
        else:
            self.tab_movable[int(index)] = bool(movable)

    def isMovable(self, index=None):
        if index is None:
            if self._movable is None:
                self._movable = QtWidgets.QTabBar.isMovable(self)
            return self._movable
        return self.tab_movable.get(index, self._movable)

    def indexAtPos(self, point):
        for index in range(self.count()):
            if self.tabRect(index).contains(point):
                return index

    def mousePressEvent(self, event):
        index = self.indexAtPos(event.pos())
        if not self.tab_movable.get(index, self.isMovable()):
            QtWidgets.QTabBar.setMovable(self, False)  # disable dragging until they release the mouse
        return QtWidgets.QTabBar.mousePressEvent(self, event)

    def mouseReleaseEvent(self, event):
        if self.isMovable():
            # Restore this in case it was temporarily disabled by mousePressEvent
            QtWidgets.QTabBar.setMovable(self, True)
        return QtWidgets.QTabBar.mouseReleaseEvent(self, event)

    def tabLayoutChange(self):
        total_height = 0
        for index in range(self.count()):
            tabRect = self.tabRect(index)
            total_height += tabRect.height()
        if total_height > self.parent().height():
            # Don't paint over the top of the scroll buttons:
            scroll_buttons_area_height = 2*max(self.style().pixelMetric(QtWidgets.QStyle.PM_TabBarScrollButtonWidth),
                                               qapplication.globalStrut().width())
            self.paint_clip = self.width(), self.parent().height() - scroll_buttons_area_height
        else:
            self.paint_clip = None

    def paintEvent(self, event):
        painter = QtWidgets.QStylePainter(self)
        if self.paint_clip is not None:
            painter.setClipRect(0, 0, *self.paint_clip)

        option = QtWidgets.QStyleOptionTab()
        for index in range(self.count()):
            tabRect = self.tabRect(index)
            self.initStyleOption(option, index)
            painter.drawControl(QtWidgets.QStyle.CE_TabBarTabShape, option)
            if not self.tabIcon(index).isNull():
                icon = self.tabIcon(index).pixmap(self.iconSize())
                alignment = QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter
                tabRect.moveLeft(10)
                painter.drawItemPixmap(tabRect, alignment, icon)
                tabRect.moveLeft(self.iconSize().width() + 15)
            else:
                tabRect.moveLeft(10)
            painter.drawText(tabRect, QtCore.Qt.AlignVCenter, self.tabText(index))
        if self.paint_clip is not None:
            x_clip, y_clip = self.paint_clip
            painter.setClipping(False)
            palette = self.palette()
            mid_color = palette.color(QtGui.QPalette.Mid)
            painter.setPen(mid_color)
            painter.drawLine(0, y_clip, x_clip, y_clip)
        painter.end()


    def tabSizeHint(self, index):
        fontmetrics = QtGui.QFontMetrics(self.font())
        text_width = fontmetrics.width(self.tabText(index))
        text_height = fontmetrics.height()
        height = text_height + 15
        height = max(self.minheight, height)
        width = text_width + 15

        button = self.tabButton(index, QtWidgets.QTabBar.RightSide)
        if button is not None:
            height = max(height, button.height() + 7)
            # Same amount of space around the button horizontally as it has vertically:
            width += button.width() + height - button.height()
        width = max(self.minwidth, width)
        return QtCore.QSize(width, height)

    def setTabButton(self, index, geometry, button):
        if not isinstance(button, TabToolButton):
            raise TypeError('Not a TabToolButton, won\'t paint correctly. Use a TabToolButton')
        result = QtWidgets.QTabBar.setTabButton(self, index, geometry, button)
        button.move(*button.get_correct_position())
        return result


class TabToolButton(QtWidgets.QToolButton):
    def __init__(self, *args, **kwargs):
        QtWidgets.QToolButton.__init__(self, *args, **kwargs)
        self.setFocusPolicy(QtCore.Qt.NoFocus)

    def paintEvent(self, event):
        painter = QtWidgets.QStylePainter(self)
        paint_clip = self.parent().paint_clip
        if paint_clip is not None:
            point = QtCore.QPoint(*paint_clip)
            global_point = self.parent().mapToGlobal(point)
            local_point = self.mapFromGlobal(global_point)
            painter.setClipRect(0, 0, local_point.x(), local_point.y())
        option = QtWidgets.QStyleOptionToolButton()
        self.initStyleOption(option)
        painter.drawComplexControl(QtWidgets.QStyle.CC_ToolButton, option)

    def get_correct_position(self):
        parent = self.parent()
        for index in range(parent.count()):
            if parent.tabButton(index, QtWidgets.QTabBar.RightSide) is self:
                break
        else:
            raise LookupError('Tab not found')
        tabRect = parent.tabRect(index)
        tab_x, tab_y, tab_width, tab_height = tabRect.x(), tabRect.y(), tabRect.width(), tabRect.height()
        size = self.sizeHint()
        width = size.width()
        height = size.height()
        padding = int((tab_height - height) / 2)
        correct_x = tab_x + tab_width - width - padding
        correct_y = tab_y + padding
        return correct_x, correct_y

    def moveEvent(self, event):
        try:
            correct_x, correct_y = self.get_correct_position()
        except LookupError:
            return # Things aren't initialised yet
        if self.x() != correct_x or self.y() != correct_y:
            # Move back! I shall not be moved!
            self.move(correct_x, correct_y)
        return QtWidgets.QToolButton.moveEvent(self, event)


class FingerTabWidget(QtWidgets.QTabWidget):

    """A QTabWidget equivalent which uses our FingerTabBarWidget"""

    def __init__(self, parent, *args):
        QtWidgets.QTabWidget.__init__(self, parent, *args)
        self.setTabBar(FingerTabBarWidget(self))

    def addTab(self, *args, **kwargs):
        closeable = kwargs.pop('closable', False)
        index = QtWidgets.QTabWidget.addTab(self, *args, **kwargs)
        self.setTabClosable(index, closeable)
        return index

    def setTabClosable(self, index, closable):
        right_button = self.tabBar().tabButton(index, QtWidgets.QTabBar.RightSide)
        if closable:
            if not right_button:
                # Make one:
                close_button = TabToolButton(self.parent())
                close_button.setIcon(QtGui.QIcon(':/qtutils/fugue/cross'))
                self.tabBar().setTabButton(index, QtWidgets.QTabBar.RightSide, close_button)
                close_button.clicked.connect(lambda: self._on_close_button_clicked(close_button))
        else:
            if right_button:
                # Get rid of it:
                self.tabBar().setTabButton(index, QtWidgets.QTabBar.RightSide, None)

    def _on_close_button_clicked(self, button):
        for index in range(self.tabBar().count()):
            if self.tabBar().tabButton(index, QtWidgets.QTabBar.RightSide) is button:
                self.tabCloseRequested.emit(index)
                break


class ItemView(object):
    """Mixin for QTableView and QTreeView that emits a custom signal leftClicked(index)
    after a left click on a valid index, and doubleLeftClicked(index) (in addition) on
    double click. Also has modified tab and arrow key behaviour and custom selection
    highlighting."""
    leftClicked = Signal(QtCore.QModelIndex)
    doubleLeftClicked = Signal(QtCore.QModelIndex)

    COLOR_HIGHLIGHT = "#40308CC6" # Semitransparent blue

    def __init__(self, *args):
        super(ItemView, self).__init__(*args)
        self._pressed_index = None
        self._double_click = False
        self.setAutoScroll(False)
        p = self.palette()
        for group in [QtGui.QPalette.Active, QtGui.QPalette.Inactive]:
            p.setColor(
                group,
                QtGui.QPalette.Highlight,
                QtGui.QColor(self.COLOR_HIGHLIGHT))
            p.setColor(
                group,
                QtGui.QPalette.HighlightedText,
                p.color(QtGui.QPalette.Active, QtGui.QPalette.Foreground)
            )
        self.setPalette(p)

    def mousePressEvent(self, event):
        result = super(ItemView, self).mousePressEvent(event)
        index = self.indexAt(event.pos())
        if event.button() == QtCore.Qt.LeftButton and index.isValid():
            self._pressed_index = self.indexAt(event.pos())
        return result

    def leaveEvent(self, event):
        result = super(ItemView, self).leaveEvent(event)
        self._pressed_index = None
        self._double_click = False
        return result

    def mouseDoubleClickEvent(self, event):
        # Ensure our left click event occurs regardless of whether it is the
        # second click in a double click or not
        result = super(ItemView, self).mouseDoubleClickEvent(event)
        index = self.indexAt(event.pos())
        if event.button() == QtCore.Qt.LeftButton and index.isValid():
            self._pressed_index = self.indexAt(event.pos())
            self._double_click = True
        return result

    def mouseReleaseEvent(self, event):
        result = super(ItemView, self).mouseReleaseEvent(event)
        index = self.indexAt(event.pos())
        if event.button() == QtCore.Qt.LeftButton and index.isValid() and index == self._pressed_index:
            self.leftClicked.emit(index)
            if self._double_click:
                self.doubleLeftClicked.emit(index)
        self._pressed_index = None
        self._double_click = False
        return result

    def keyPressEvent(self, event):
        if event.key() in [QtCore.Qt.Key_Space, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Return]:
            item = self.model().itemFromIndex(self.currentIndex())
            if item.isEditable():
                # Space/enter edits editable items:
                self.edit(self.currentIndex())
            else:
                # Space/enter on non-editable items simulates a left click:
                self.leftClicked.emit(self.currentIndex())
        return super(ItemView, self).keyPressEvent(event)

    def moveCursor(self, cursor_action, keyboard_modifiers):
        current_index = self.currentIndex()
        current_row, current_column = current_index.row(), current_index.column()
        if cursor_action == QtWidgets.QAbstractItemView.MoveUp:
            return current_index.sibling(current_row - 1, current_column)
        elif cursor_action == QtWidgets.QAbstractItemView.MoveDown:
            return current_index.sibling(current_row + 1, current_column)
        elif cursor_action == QtWidgets.QAbstractItemView.MoveLeft:
            return current_index.sibling(current_row, current_column - 1)
        elif cursor_action == QtWidgets.QAbstractItemView.MoveRight:
            return current_index.sibling(current_row, current_column + 1)
        elif cursor_action == QtWidgets.QAbstractItemView.MovePrevious:
            return current_index.sibling(current_row, current_column - 1)
        elif cursor_action == QtWidgets.QAbstractItemView.MoveNext:
            return current_index.sibling(current_row, current_column + 1)
        else:
            return super(ItemView, self).moveCursor(cursor_action, keyboard_modifiers)


class TreeView(ItemView, QtWidgets.QTreeView):
    """Treeview version of our customised ItemView"""
    def __init__(self, parent=None):
        super(TreeView, self).__init__(parent)
        # Set columns to their minimum size, disabling resizing. Caller may still
        # configure a specific section to stretch:
        self.header().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeToContents
        )
        self.setItemDelegate(ItemDelegate(self))


class TableView(ItemView, QtWidgets.QTableView):
    """TableView version of our customised ItemView"""
    def __init__(self, parent=None):
        super(TableView, self).__init__(parent)
        # Set rows and columns to the minimum size, disabling interactive resizing.
        # Caller may still configure a specific column to stretch:
        self.verticalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeToContents
        )
        self.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeToContents
        )
        self.horizontalHeader().sectionResized.connect(self.on_column_resized)
        self.setItemDelegate(ItemDelegate(self))
        self.verticalHeader().hide()
        self.setShowGrid(False)
        self.horizontalHeader().setHighlightSections(False)

    def on_column_resized(self, col):
        for row in range(self.model().rowCount()):
            self.resizeRowToContents(row)


class AlternatingColorModel(QtGui.QStandardItemModel):

    def __init__(self, view):
        QtGui.QStandardItemModel.__init__(self)
        # How much darker in each channel is the alternate base color compared
        # to the base color?
        self.view = view
        palette = view.palette()
        self.normal_color = palette.color(QtGui.QPalette.Base)
        self.alternate_color = palette.color(QtGui.QPalette.AlternateBase)
        r, g, b, a = self.normal_color.getRgb()
        alt_r, alt_g, alt_b, alt_a = self.alternate_color.getRgb()
        self.delta_r = alt_r - r
        self.delta_g = alt_g - g
        self.delta_b = alt_b - b
        self.delta_a = alt_a - a

        # A cache, store brushes so we don't have to recalculate them. Is faster.
        self.bg_brushes = {}

    def get_bgbrush(self, normal_brush, alternate, selected):
        """Get cell colour as a function of its ordinary colour, whether it is on an odd
        row, and whether it is selected."""
        normal_rgb = normal_brush.color().getRgb() if normal_brush is not None else None
        try:
            return self.bg_brushes[normal_rgb, alternate, selected]
        except KeyError:
            pass
        # Get the colour of the cell with alternate row shading:
        if normal_rgb is None:
            # No colour has been set. Use palette colours:
            if alternate:
                bg_color = self.alternate_color
            else:
                bg_color = self.normal_color
        else:
            bg_color = normal_brush.color()
            if alternate:
                # Modify alternate rows:
                r, g, b, a = normal_rgb
                alt_r = min(max(r + self.delta_r, 0), 255)
                alt_g = min(max(g + self.delta_g, 0), 255)
                alt_b = min(max(b + self.delta_b, 0), 255)
                alt_a = min(max(a + self.delta_a, 0), 255)
                bg_color = QtGui.QColor(alt_r, alt_g, alt_b, alt_a)

        # If parent is a TableView, we handle selection highlighting as part of the
        # background colours:
        if selected and isinstance(self.view, QtWidgets.QTableView):
            # Overlay highlight colour:
            r_s, g_s, b_s, a_s = QtGui.QColor(ItemView.COLOR_HIGHLIGHT).getRgb()
            r_0, g_0, b_0, a_0 = bg_color.getRgb()
            rgb = composite_colors(r_0, g_0, b_0, a_0, r_s, g_s, b_s, a_s)
            bg_color = QtGui.QColor(*rgb)

        brush = QtGui.QBrush(bg_color)
        self.bg_brushes[normal_rgb, alternate, selected] = brush
        return brush

    def data(self, index, role):
        """When background color data is being requested, returns modified colours for
        every second row, according to the palette of the view. This has the effect of
        making the alternate colours visible even when custom colors have been set - the
        same shading will be applied to the custom colours. Only really looks sensible
        when the normal and alternate colors are similar. Also applies selection
        highlight colour (using ItemView.COLOR_HIGHLIGHT), similarly with alternate-row
        shading, for the case of a QTableView."""
        if role == QtCore.Qt.BackgroundRole:
            normal_brush = QtGui.QStandardItemModel.data(self, index, QtCore.Qt.BackgroundRole)
            selected = index in self.view.selectedIndexes()
            alternate = index.row() % 2
            return self.get_bgbrush(normal_brush, alternate, selected)
        return QtGui.QStandardItemModel.data(self, index, role)


class Editor(QtWidgets.QTextEdit):
    """Popup editor with word wrapping and automatic resizing."""
    def __init__(self, parent):
        QtWidgets.QTextEdit.__init__(self, parent)
        self.setWordWrapMode(QtGui.QTextOption.WordWrap)
        self.setAcceptRichText(False)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.textChanged.connect(self.update_size)
        self.initial_height = None

    def update_size(self):
        if self.initial_height is not None:
            # Temporarily shrink back to the initial height, just so that the document
            # size below returns the preferred size rather than the current size.
            # QTextDocument doesn't have a sizeHint of minimumSizeHint method, so this
            # is the best we can do to get its minimum size.
            self.setFixedHeight(self.initial_height)
        preferred_height = self.document().size().toSize().height()
        # Do not shrink smaller than the initial height:
        if self.initial_height is not None and preferred_height >= self.initial_height:
            self.setFixedHeight(preferred_height)

    def resizeEvent(self, event):
        result = QtWidgets.QTextEdit.resizeEvent(self, event)
        # Record the initial height after it is first set:
        if self.initial_height is None:
            self.initial_height = self.height()
        return result


class ItemDelegate(QtWidgets.QStyledItemDelegate):

    """An item delegate with a larger row height and column width, faint grey vertical
    lines between columns, and a custom editor for handling multi-line data"""
    MIN_ROW_HEIGHT = 22
    EXTRA_ROW_HEIGHT = 6
    EXTRA_COL_WIDTH = 20

    def __init__(self, *args, **kwargs):
        QtWidgets.QStyledItemDelegate.__init__(self, *args, **kwargs)
        self._pen = QtGui.QPen()
        self._pen.setWidth(1)
        self._pen.setColor(QtGui.QColor.fromRgb(128, 128, 128, 64))

    def sizeHint(self, *args):
        size = QtWidgets.QStyledItemDelegate.sizeHint(self, *args)
        if size.height() <= self.MIN_ROW_HEIGHT:
            height = self.MIN_ROW_HEIGHT
        else:
            # Esnure cells with multiple lines of text still have some padding:
            height = size.height() + self.EXTRA_ROW_HEIGHT
        return QtCore.QSize(size.width() + self.EXTRA_COL_WIDTH, height)

    def paint(self, painter, option, index):
        if isinstance(self.parent(), QtWidgets.QTableView):
            # Disable rendering of selection highlight for TableViews, they handle
            # it themselves with the background colour data:
            option.state &= ~(QtWidgets.QStyle.State_Selected)
        QtWidgets.QStyledItemDelegate.paint(self, painter, option, index)
        if index.column() > 0:
            painter.setPen(self._pen)
            painter.drawLine(option.rect.topLeft(), option.rect.bottomLeft())

    def eventFilter(self, obj, event):
        """Filter events before they get to the editor, so that editing is ended when
        the user presses tab, shift-tab or enter (which otherwise would not end editing
        in a QTextEdit)."""
        if event.type() == QtCore.QEvent.KeyPress:
            if event.key() in [QtCore.Qt.Key_Enter, QtCore.Qt.Key_Return]:
                # Allow shift-enter
                if not event.modifiers() & QtCore.Qt.ShiftModifier:
                    self.commitData.emit(obj)
                    self.closeEditor.emit(obj)
                    return True
            elif event.key() == QtCore.Qt.Key_Tab:
                self.commitData.emit(obj)
                self.closeEditor.emit(obj, QtWidgets.QStyledItemDelegate.EditNextItem)
                return True
            elif event.key() == QtCore.Qt.Key_Backtab:
                self.commitData.emit(obj)
                self.closeEditor.emit(obj, QtWidgets.QStyledItemDelegate.EditPreviousItem)
                return True
        return QtWidgets.QStyledItemDelegate.eventFilter(self, obj, event)

    def createEditor(self, parent, option, index):
        return Editor(parent)

    def setEditorData(self, editor, index):
        editor.setPlainText(index.data())
        font = index.data(QtCore.Qt.FontRole)
        default_font = qapplication.font(self.parent())
        if font is None:
            font = default_font
        font.setPointSize(default_font.pointSize())
        editor.setFont(font)
        font_height = QtGui.QFontMetrics(font).height()
        padding = (self.MIN_ROW_HEIGHT - font_height) / 2 - 1
        editor.document().setDocumentMargin(padding)
        editor.selectAll()
        
    def setModelData(self, editor, model, index):
        model.setData(index, editor.toPlainText())
