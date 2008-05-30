# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4
#
# Flumotion - a streaming media server
# Copyright (C) 2004,2005,2006,2007,2008 Fluendo, S.L. (www.fluendo.com).
# All rights reserved.

# This file may be distributed and/or modified under the terms of
# the GNU General Public License version 2 as published by
# the Free Software Foundation.
# This file is distributed without any warranty; without even the implied
# warranty of merchantability or fitness for a particular purpose.
# See "LICENSE.GPL" in the source distribution for more information.

# Licensees having purchased or holding a valid Flumotion Advanced
# Streaming Server license may use this file in accordance with the
# Flumotion Advanced Streaming Server Commercial License Agreement.
# See "LICENSE.Flumotion" in the source distribution for more information.

# Headers in this file shall remain intact.

import gettext
import os

import gobject
import gtk

from flumotion.common import componentui, log
from flumotion.common.common import pathToModuleName
from flumotion.common.errors import NoBundleError, SleepingComponentError
from flumotion.common.planet import AdminComponentState, moods

# ensure unjellier registered
componentui # pyflakes

__version__ = "$Rev$"
_ = gettext.gettext
_DEBUG_ONLY_PAGES = ['Eaters', 'Feeders']
(COMPONENT_UNSET,
 COMPONENT_INACTIVE,
 COMPONENT_ACTIVE) = range(3)


class NodeBook(gtk.Notebook, log.Loggable):
    logCategory = 'nodebook'

    def __init__(self, admingtk):
        """
        @param admingtk: the GTK Admin with its nodes
        @type  admingtk: L{flumotion.component.base.admin_gtk.BaseAdminGtk}
        """
        self.admingtk = admingtk
        gtk.Notebook.__init__(self)
        self._debugEnabled = False
        self._pageWidgets = {}

        admingtk.setup()
        self.nodes = admingtk.getNodes()
        self._appendPages()
        self.show()

    def setDebugEnabled(self, enabled):
        """Set if debug should be enabled.
        Not all pages are visible unless debugging is set to true
        @param enable: if debug should be enabled
        """
        self._debugEnabled = enabled
        if self.admingtk:
            self.admingtk.setDebugEnabled(enabled)
        for name in _DEBUG_ONLY_PAGES:
            widget = self._pageWidgets.get(name)
            if widget is None:
                continue
            widget.set_property('visible', enabled)

    def _renderWidget(self, widget, table):
        # dumb dumb dumb dumb
        old_parent = widget.get_parent()
        if old_parent:
            old_parent.remove(widget)
        map(table.remove, table.get_children())
        table.add(widget)
        widget.show()

    def _addPage(self, name):
        node = self.nodes.get(name)
        assert node is not None, name

        table = gtk.Table(1, 1)
        table.add(gtk.Label(_('Loading UI for %s...') % name))
        label = self._getTitleLabel(node, name)
        label.show()
        self.append_page(table, label)

        d = node.render()
        d.addCallback(self._renderWidget, table)
        return table

    def _appendPages(self):
        for name in self.nodes.keys():
            table = self._addPage(name)
            self._pageWidgets[name] = table

            if name in _DEBUG_ONLY_PAGES:
                if self._debugEnabled:
                    continue
            table.show()

    def _getTitleLabel(self, node, name):
        title = node.title
        if not title:
            # FIXME: we have no way of showing an error message ?
            # This should be added so users can file bugs.
            self.warning("Component node %s does not have a "
                         "translatable title. Please file a bug." % name)

            # fall back for now
            title = name

        return gtk.Label(title)


class ComponentView(gtk.VBox, log.Loggable):
    logCategory = 'componentview'

    def __init__(self):
        gtk.VBox.__init__(self)
        self.widget_constructor = None
        self._admin = None
        self._widget = None
        self._componentState = None
        self._state = COMPONENT_UNSET
        self._callStamp = 0
        self._debugEnabled = False
        self._currentNodebook = None
        self.setSingleAdmin(None)

    # Public API

    def getDebugEnabled(self):
        """Find out if debug is enabled
        @returns: if debug is enabled
        @rtype: bool
        """
        return self._debugEnabled

    def setDebugEnabled(self, enabled):
        """Sets if debug should be enabled
        @param enabled: if debug should be enabled
        @type enabled: bool
        """
        self._debugEnabled = enabled
        if self._currentNodebook:
            self._currentNodebook.setDebugEnabled(enabled)

    def activateComponent(self, component):
        """Activates a component in the view
        @param component: component to show
        @type component: L{flumotion.common.component.AdminComponentState}
        """
        self._setState(COMPONENT_UNSET)
        if component:
            self._componentState = component
            self._setState(COMPONENT_INACTIVE)

    def setSingleAdmin(self, admin):
        """Sets a single global admin for the component view
        @param admin: the admin
        @type admin: L{flumotion.admin.model.AdminModel}
        """
        self._admin = admin

    def getAdminForComponent(self, component):
        """Get the admin for a specific component
        @param component: component 
        @type component: L{flumotion.common.component.AdminComponentState}
        @returns: the admin
        @rtype: L{flumotion.admin.model.AdminModel}
        """
        # override me to do e.g. multi.getAdminForComponent
        return self._admin

    # Private

    def _packWidget(self, widget):
        assert self._widget == None
        self._widget = widget
        self._widget.show()
        self.pack_start(self._widget, True, True)
        self._currentNodebook = widget
        self._currentNodebook.setDebugEnabled(self._debugEnabled)
        return self._widget

    def _getWidgetConstructor(self, state):
        def notComponentState():
            return gtk.Label('')

        def noBundle(failure):
            failure.trap(NoBundleError)
            self.debug(
                'No specific GTK admin for this component, using default')
            return ("flumotion/component/base/admin_gtk.py", "BaseAdminGtk")

        def oldVersion(failure):
            # This is compatibility with platform-3
            # FIXME: It would be better to do this using strict
            #        version checking of the manager

            # File ".../flumotion/manager/admin.py", line 278, in
            #   perspective_getEntryByType
            # exceptions.AttributeError: 'str' object has no attribute 'get'
            failure.trap(AttributeError)

            return admin.callRemote('getEntryByType', state, 'admin/gtk')

        def gotEntryPoint((filename, procname)):
            # The manager always returns / as a path separator, replace them
            # with the separator since the rest of our infrastructure depends
            # on that.
            filename = filename.replace('/', os.path.sep)
            # getEntry for admin/gtk returns a factory function for creating
            # flumotion.component.base.admin_gtk.BaseAdminGtk subclass instances
            modname = pathToModuleName(filename)
            return admin.getBundledFunction(modname, procname)

        def gotFactory(factory):
            # instantiate from factory and wrap in a NodeBook
            return lambda: NodeBook(factory(state, admin))

        def sleepingComponent(failure):
            failure.trap(SleepingComponentError)
            return lambda: gtk.Label(_('Component %s is still sleeping') %
                                     state.get('name'))

        admin = self.getAdminForComponent(state)
        if not isinstance(state, AdminComponentState):
            return notComponentState

        componentType = state.get('type')
        d = admin.callRemote('getEntryByType', componentType, 'admin/gtk')
        d.addErrback(oldVersion)
        d.addErrback(noBundle)
        d.addCallback(gotEntryPoint)
        d.addCallback(gotFactory)
        d.addErrback(sleepingComponent)
        return d

    def _componentUnsetToInactive(self):
        def invalidate(_):
            self._setState(COMPONENT_UNSET)
        def set(state, key, value):
            if key == 'mood':
                if value not in [moods.lost.value,
                                 moods.sleeping.value,
                                 moods.sad.value]:
                    self._setState(COMPONENT_ACTIVE)
                else:
                    self._setState(COMPONENT_INACTIVE)

        assert self._componentState is not None
        self._componentState.addListener(
            self, invalidate=invalidate, set=set)
        if self._componentState.hasKey('mood'):
            set(self._componentState, 'mood', self._componentState.get('mood'))

    def _componentInactiveToActive(self):
        def gotWidgetConstructor(proc, callStamp):
            if callStamp != self._callStamp:
                # in the time that _get_widget_constructor was running,
                # perhaps the user selected another component; only update
                # the ui if that did not happen
                self.debug('ignoring widget constructor %r, state %d, '
                           'callstamps %d/%d', proc, self._state,
                           callStamp, self._callStamp)
                return
            widget = proc()
            return self._packWidget(widget)

        self._callStamp += 1
        callStamp = self._callStamp
        d = self._getWidgetConstructor(self._componentState)
        d.addCallback(gotWidgetConstructor, callStamp)

    def _componentActiveToInactive(self):
        # prevent got_widget_constructor from adding the widget above
        self._callStamp += 1
        if not self._widget:
            return

        self.remove(self._widget)
        # widget maybe a gtk.Label or a NodeBook
        if hasattr(self._widget, 'admingtk'):
            if self._widget.admingtk:
                # needed for compatibility with managers with old code
                if hasattr(self._widget.admingtk, 'cleanup'):
                    self._widget.admingtk.cleanup()
                self._widget.admingtk = None
        self._widget = None

    def _componentInactiveToUnset(self):
        self._componentState.removeListener(self)
        self._componentState = None

    def _setState(self, state):
        uptable = [self._componentUnsetToInactive,
                   self._componentInactiveToActive]
        downtable = [self._componentInactiveToUnset,
                     self._componentActiveToInactive]
        if self._state < state:
            while self._state < state:
                self.log('component %r state change: %d++',
                         self._componentState, self._state)
                self._state += 1
                uptable[self._state - 1]()
        else:
            while self._state > state:
                self.log('component %r state change: %d--',
                         self._componentState, self._state)
                self._state -= 1
                downtable[self._state]()

gobject.type_register(ComponentView)
