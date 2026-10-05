/*
 * Copyright 2010-2012 Intel Corporation
 * Copyright 2013 Raspberry Pi Foundation
 * Copyright 2011-2012,2020 Collabora, Ltd.
 * Copyright 2026 AuraDE Contributors
 *
 * Permission is hereby granted, free of charge, to any person obtaining a
 * copy of this software and associated documentation files (the "Software"),
 * to deal in the Software without restriction, including without limitation
 * the rights to use, copy, modify, merge, publish, distribute, sublicense,
 * and/or sell copies of the Software, and to permit persons to whom the
 * Software is furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice (including the next
 * paragraph) shall be included in all copies or substantial portions of the
 * Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
 * THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
 * FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
 * DEALINGS IN THE SOFTWARE.
 */

/*
 * The weston shell of the AuraDE session, from weston 15's kiosk-shell.
 *
 * Like kiosk-shell, every top-level surface is shown fullscreen, and each
 * output shows one surface tree. What it adds is what Ash needs to spread
 * its desktop over several monitors, one host window on each:
 *
 *  - A surface asked onto an output, with xdg_toplevel.set_fullscreen and
 *    an output, moves there at any time, and the output it leaves shows the
 *    surface that was under it. kiosk-shell settles a surface's output once.
 *
 *  - The pointer crosses from one output to the next where Ash's display
 *    arrangement has them meet, measured in Ash's logical pixels, so the
 *    arrangement in Settings is the one the mouse follows, and a monitor at
 *    200% meets one at 100% where Ash shows them meeting. Ash writes the
 *    arrangement to $XDG_RUNTIME_DIR/aurade/display-layout, one line per
 *    display: the output's name, then x, y, width and height.
 *
 *  - A drag that starts in one Ash host window carries on into the host
 *    window on the next monitor, so a window or a tab can be dragged from
 *    one monitor to another.
 */

#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <limits.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/inotify.h>
#include <sys/stat.h>
#include <unistd.h>

#include <libweston/config-parser.h>
#include <libweston/desktop.h>
#include <libweston/libweston.h>
#include <libweston/shell-utils.h>
#include <weston.h>

#ifndef container_of
#define container_of(ptr, type, member) ({				\
	const __typeof__( ((type *)0)->member ) *__mptr = (ptr);	\
	(type *)( (char *)__mptr - offsetof(type,member) );})
#endif

#define AURADE_LAYOUT_MAX 16

struct aurade_layout_entry {
	char name[64];
	double x, y, width, height;
};

struct aurade_shell {
	struct weston_compositor *compositor;
	struct weston_desktop *desktop;

	struct wl_listener destroy_listener;
	struct wl_listener output_created_listener;
	struct wl_listener output_resized_listener;
	struct wl_listener output_moved_listener;
	struct wl_listener seat_created_listener;
	struct wl_listener session_listener;

	struct weston_layer background_layer;
	struct weston_layer normal_layer;
	struct weston_layer inactive_layer;

	struct wl_list output_list;
	struct wl_list seat_list;

	struct weston_config *config;

	/* Ash's arrangement of the displays, from the layout file. */
	struct aurade_layout_entry layout[AURADE_LAYOUT_MAX];
	int layout_count;
	char *layout_dir;
	int inotify_fd;
	struct wl_event_source *inotify_source;

	/* The pointer grab weston would use, which ours passes everything to. */
	const struct weston_pointer_grab_interface *weston_grab;
	struct weston_pointer_grab_interface pointer_grab;
	bool pointer_grab_installed;
};

struct aurade_shell_surface {
	struct weston_desktop_surface *desktop_surface;
	struct weston_view *view;

	struct aurade_shell *shell;

	struct aurade_shell_output *output;
	struct wl_listener output_destroy_listener;

	struct wl_signal destroy_signal;

	struct wl_signal parent_destroy_signal;
	struct wl_listener parent_destroy_listener;
	struct aurade_shell_surface *parent;

	struct wl_list surface_tree_list;
	struct wl_list surface_tree_link;

	int focus_count;

	int32_t last_width, last_height;
};

struct aurade_shell_seat {
	struct weston_seat *seat;
	struct wl_listener seat_destroy_listener;
	struct wl_listener caps_listener;
	struct weston_surface *focused_surface;

	struct wl_list link;	/** aurade_shell::seat_list */
};

struct aurade_shell_output {
	struct weston_output *output;
	struct wl_listener output_destroy_listener;
	struct weston_curtain *curtain;

	/* Until the output paints its first frame. */
	struct wl_listener first_latch_listener;
	struct wl_event_source *start_watchdog;
	int start_watchdog_ticks;

	struct aurade_shell *shell;
	struct wl_list link;

	struct wl_list *active_surface_tree;
};

/* The pointer grab callbacks get no data of their own, and a compositor has
 * one shell. */
static struct aurade_shell *the_shell;

static struct aurade_shell_surface *
get_aurade_shell_surface(struct weston_surface *surface)
{
	struct weston_desktop_surface *desktop_surface =
		weston_surface_get_desktop_surface(surface);

	if (desktop_surface)
		return weston_desktop_surface_get_user_data(desktop_surface);

	return NULL;
}

static void
aurade_shell_seat_handle_destroy(struct wl_listener *listener, void *data);

static struct aurade_shell_seat *
get_aurade_shell_seat(struct weston_seat *seat)
{
	struct wl_listener *listener;

	if (!seat)
		return NULL;

	listener = wl_signal_get(&seat->destroy_signal,
				 aurade_shell_seat_handle_destroy);

	if (!listener)
		return NULL;

	return container_of(listener,
			    struct aurade_shell_seat, seat_destroy_listener);
}

static struct weston_seat *
get_aurade_shell_first_seat(struct aurade_shell *shell)
{
	struct wl_list *node;
	struct weston_compositor *compositor = shell->compositor;

	if (wl_list_empty(&compositor->seat_list))
		return NULL;

	node = compositor->seat_list.next;
	return container_of(node, struct weston_seat, link);
}

/*
 * aurade_shell_surface
 */

static void
aurade_shell_surface_set_output(struct aurade_shell_surface *shsurf,
				struct aurade_shell_output *shoutput);
static void
aurade_shell_surface_set_parent(struct aurade_shell_surface *shsurf,
				struct aurade_shell_surface *parent);
static void
aurade_shell_output_set_active_surface_tree(struct aurade_shell_output *shoutput,
					    struct aurade_shell_surface *shroot);
static void
aurade_shell_output_raise_surface_subtree(struct aurade_shell_output *shoutput,
					  struct aurade_shell_surface *shroot);

static void
aurade_shell_surface_notify_parent_destroy(struct wl_listener *listener,
					   void *data)
{
	struct aurade_shell_surface *shsurf =
		container_of(listener,
			     struct aurade_shell_surface, parent_destroy_listener);

	aurade_shell_surface_set_parent(shsurf, shsurf->parent->parent);
}

static void
aurade_shell_surface_notify_output_destroy(struct wl_listener *listener,
					   void *data)
{
	struct aurade_shell_surface *shsurf =
		container_of(listener,
			     struct aurade_shell_surface, output_destroy_listener);

	aurade_shell_surface_set_output(shsurf, NULL);
}

static struct aurade_shell_surface *
aurade_shell_surface_get_parent_root(struct aurade_shell_surface *shsurf)
{
	struct aurade_shell_surface *root = shsurf;
	while (root->parent)
		root = root->parent;
	return root;
}

static struct aurade_shell_output *
aurade_shell_find_empty_output(struct aurade_shell *shell)
{
	struct aurade_shell_output *shoutput;

	wl_list_for_each(shoutput, &shell->output_list, link) {
		if (shoutput->output && !shoutput->active_surface_tree)
			return shoutput;
	}
	return NULL;
}

static struct aurade_shell_output *
aurade_shell_surface_find_best_output(struct aurade_shell_surface *shsurf)
{
	struct weston_output *output;
	struct aurade_shell_output *shoutput;
	struct aurade_shell_surface *root;

	/* Always use current output if any. */
	if (shsurf->output)
		return shsurf->output;

	/* Group all related windows in the same output. */
	root = aurade_shell_surface_get_parent_root(shsurf);
	if (root->output)
		return root->output;

	/* A new top-level goes where nothing is shown yet, which is where the
	 * next Ash host window is about to be asked to go anyway. */
	shoutput = aurade_shell_find_empty_output(shsurf->shell);
	if (shoutput)
		return shoutput;

	output = weston_shell_utils_get_focused_output(shsurf->shell->compositor);
	if (output)
		return weston_output_get_shell_private(output);

	output = weston_shell_utils_get_default_output(shsurf->shell->compositor);
	if (output)
		return weston_output_get_shell_private(output);

	return NULL;
}

static void
aurade_shell_surface_set_output(struct aurade_shell_surface *shsurf,
				struct aurade_shell_output *shoutput)
{
	shsurf->output = shoutput;

	if (shsurf->output_destroy_listener.notify) {
		wl_list_remove(&shsurf->output_destroy_listener.link);
		shsurf->output_destroy_listener.notify = NULL;
	}

	if (!shsurf->output)
		return;

	shsurf->output_destroy_listener.notify =
		aurade_shell_surface_notify_output_destroy;
	wl_signal_add(&shsurf->output->output->destroy_signal,
		      &shsurf->output_destroy_listener);
}

/* Another root surface tree that lives on |shoutput|, other than |shroot|'s,
 * topmost first: what an output shows when its surface moves away. */
static struct aurade_shell_surface *
aurade_shell_output_find_other_root(struct aurade_shell_output *shoutput,
				    struct aurade_shell_surface *shroot)
{
	struct aurade_shell *shell = shoutput->shell;
	struct weston_layer *layers[] = {
		&shell->normal_layer, &shell->inactive_layer
	};
	struct weston_view *view;
	unsigned int i;

	for (i = 0; i < sizeof(layers) / sizeof(layers[0]); i++) {
		wl_list_for_each(view, &layers[i]->view_list.link,
				 layer_link.link) {
			struct aurade_shell_surface *s =
				get_aurade_shell_surface(view->surface);

			if (!s || s->parent || s == shroot)
				continue;
			if (s->output == shoutput)
				return s;
		}
	}
	return NULL;
}

/* Moves a root surface tree to another output: the output it leaves shows
 * whatever else lives there, and the one it reaches shows it. */
static void
aurade_shell_surface_move_to_output(struct aurade_shell_surface *shsurf,
				    struct aurade_shell_output *shoutput)
{
	struct aurade_shell_output *old = shsurf->output;
	struct weston_surface *surface =
		weston_desktop_surface_get_surface(shsurf->desktop_surface);

	if (old == shoutput)
		return;

	if (old && old->active_surface_tree == &shsurf->surface_tree_list) {
		struct aurade_shell_surface *other =
			aurade_shell_output_find_other_root(old, shsurf);

		/* Let go without hiding this tree, then show the other. */
		old->active_surface_tree = NULL;
		aurade_shell_output_set_active_surface_tree(old, other);
	}

	aurade_shell_surface_set_output(shsurf, shoutput);
	if (!shoutput)
		return;

	if (weston_surface_is_mapped(surface)) {
		aurade_shell_output_set_active_surface_tree(shoutput, shsurf);
		weston_shell_utils_center_on_output(shsurf->view,
						    shoutput->output);
		weston_view_update_transform(shsurf->view);
	}
}

static void
aurade_shell_surface_set_fullscreen(struct aurade_shell_surface *shsurf,
				    struct aurade_shell_output *shoutput)
{
	if (!shoutput)
		shoutput = aurade_shell_surface_find_best_output(shsurf);

	if (!shsurf->parent)
		aurade_shell_surface_move_to_output(shsurf, shoutput);
	else
		aurade_shell_surface_set_output(shsurf, shoutput);

	weston_desktop_surface_set_fullscreen(shsurf->desktop_surface, true);
	if (shsurf->output)
		weston_desktop_surface_set_size(shsurf->desktop_surface,
						shsurf->output->output->width,
						shsurf->output->output->height);
}

static void
aurade_shell_surface_set_normal(struct aurade_shell_surface *shsurf)
{
	if (!shsurf->output)
		aurade_shell_surface_set_output(shsurf,
			aurade_shell_surface_find_best_output(shsurf));

	weston_desktop_surface_set_fullscreen(shsurf->desktop_surface, false);
	weston_desktop_surface_set_maximized(shsurf->desktop_surface, false);
	weston_desktop_surface_set_size(shsurf->desktop_surface, 0, 0);
}

static bool
aurade_shell_surface_is_surface_in_tree(struct aurade_shell_surface *shsurf,
					struct aurade_shell_surface *shroot)
{
	struct aurade_shell_surface *s;

	wl_list_for_each(s, &shroot->surface_tree_list, surface_tree_link) {
		if (s == shsurf)
			return true;
	}

	return false;
}

static bool
aurade_shell_surface_is_descendant_of(struct aurade_shell_surface *shsurf,
				      struct aurade_shell_surface *ancestor)
{
	while (shsurf) {
		if (shsurf == ancestor)
			return true;
		shsurf = shsurf->parent;
	}

	return false;
}

static void
active_surface_tree_move_element_to_top(struct wl_list *active_surface_tree,
					struct wl_list *element)
{
	wl_list_remove(element);
	wl_list_insert(active_surface_tree, element);
}

static void
aurade_shell_surface_set_parent(struct aurade_shell_surface *shsurf,
				struct aurade_shell_surface *parent)
{
	struct aurade_shell_output *shoutput = shsurf->output;
	struct aurade_shell_surface *shroot = parent ?
		aurade_shell_surface_get_parent_root(parent) :
		aurade_shell_surface_get_parent_root(shsurf);

	/* There are cases where xdg clients call .set_parent(nil) on a surface
	 * that does not have a parent. The protocol states that this is
	 * effectively a no-op. */
	if (!parent && shsurf == shroot)
		return;

	if (shsurf->parent_destroy_listener.notify) {
		wl_list_remove(&shsurf->parent_destroy_listener.link);
		shsurf->parent_destroy_listener.notify = NULL;
	}

	shsurf->parent = parent;

	if (shsurf->parent) {
		shsurf->parent_destroy_listener.notify =
			aurade_shell_surface_notify_parent_destroy;
		wl_signal_add(&parent->parent_destroy_signal,
			      &shsurf->parent_destroy_listener);

		if (!aurade_shell_surface_is_surface_in_tree(shsurf, shroot)) {
			active_surface_tree_move_element_to_top(&shroot->surface_tree_list,
								&shsurf->surface_tree_link);
		}
		aurade_shell_surface_set_output(shsurf, NULL);
		aurade_shell_surface_set_normal(shsurf);
	} else {
		struct aurade_shell_surface *s, *tmp;

		/* Relink the child and all its descendents to a new surface
		 * tree list, with the child as root. */
		wl_list_init(&shsurf->surface_tree_list);
		wl_list_for_each_reverse_safe(s, tmp, &shroot->surface_tree_list,
					      surface_tree_link) {
			if (aurade_shell_surface_is_descendant_of(s, shsurf)) {
				active_surface_tree_move_element_to_top(&shsurf->surface_tree_list,
									&s->surface_tree_link);
			}
		}
		if (shoutput)
			aurade_shell_output_set_active_surface_tree(shoutput, shsurf);
		aurade_shell_surface_set_fullscreen(shsurf, shsurf->output);
	}
}

static void
aurade_shell_surface_reconfigure_for_output(struct aurade_shell_surface *shsurf)
{
	struct weston_desktop_surface *desktop_surface;
	struct weston_output *w_output;

	if (!shsurf->output)
		return;

	w_output = shsurf->output->output;
	desktop_surface = shsurf->desktop_surface;

	if (weston_desktop_surface_get_maximized(desktop_surface) ||
	    weston_desktop_surface_get_fullscreen(desktop_surface)) {
		weston_desktop_surface_set_size(desktop_surface,
						w_output->width,
						w_output->height);
	}

	weston_shell_utils_center_on_output(shsurf->view, w_output);
	weston_view_update_transform(shsurf->view);
}

static void
aurade_shell_surface_destroy(struct aurade_shell_surface *shsurf)
{
	wl_signal_emit(&shsurf->destroy_signal, shsurf);
	wl_list_remove(&shsurf->surface_tree_link);

	weston_desktop_surface_set_user_data(shsurf->desktop_surface, NULL);
	shsurf->desktop_surface = NULL;

	weston_desktop_surface_unlink_view(shsurf->view);

	weston_view_destroy(shsurf->view);

	if (shsurf->output_destroy_listener.notify) {
		wl_list_remove(&shsurf->output_destroy_listener.link);
		shsurf->output_destroy_listener.notify = NULL;
	}

	if (shsurf->parent_destroy_listener.notify) {
		wl_list_remove(&shsurf->parent_destroy_listener.link);
		shsurf->parent_destroy_listener.notify = NULL;
		shsurf->parent = NULL;
	}

	free(shsurf);
}

static struct aurade_shell_surface *
aurade_shell_surface_create(struct aurade_shell *shell,
			    struct weston_desktop_surface *desktop_surface)
{
	struct weston_desktop_client *client =
		weston_desktop_surface_get_client(desktop_surface);
	struct wl_client *wl_client =
		weston_desktop_client_get_client(client);
	struct weston_view *view;
	struct aurade_shell_surface *shsurf;

	view = weston_desktop_surface_create_view(desktop_surface);
	if (!view)
		return NULL;

	shsurf = calloc(1, sizeof *shsurf);
	if (!shsurf) {
		if (wl_client)
			wl_client_post_no_memory(wl_client);
		else
			weston_log("no memory to allocate shell surface\n");
		return NULL;
	}

	shsurf->desktop_surface = desktop_surface;
	shsurf->view = view;
	shsurf->shell = shell;

	weston_desktop_surface_set_user_data(desktop_surface, shsurf);

	wl_signal_init(&shsurf->destroy_signal);
	wl_signal_init(&shsurf->parent_destroy_signal);

	/* start life inserting itself as root of its own surface tree list */
	wl_list_init(&shsurf->surface_tree_list);
	wl_list_init(&shsurf->surface_tree_link);
	wl_list_insert(&shsurf->surface_tree_list, &shsurf->surface_tree_link);

	return shsurf;
}

static void
aurade_shell_surface_activate(struct aurade_shell_surface *shsurf,
			      struct aurade_shell_seat *aurade_seat,
			      uint32_t activate_flags)
{
	struct weston_desktop_surface *dsurface = shsurf->desktop_surface;
	struct weston_surface *surface =
		weston_desktop_surface_get_surface(dsurface);
	struct aurade_shell_output *shoutput = shsurf->output;

	/* keyboard focus */
	weston_view_activate_input(shsurf->view, aurade_seat->seat,
				   activate_flags);

	/* xdg-shell deactivation if there's a focused one */
	if (aurade_seat->focused_surface) {
		struct aurade_shell_surface *current_focus =
			get_aurade_shell_surface(aurade_seat->focused_surface);
		struct weston_desktop_surface *dsurface_focus;
		assert(current_focus);

		dsurface_focus = current_focus->desktop_surface;
		if (--current_focus->focus_count == 0)
			weston_desktop_surface_set_activated(dsurface_focus, false);
	}

	/* xdg-shell activation for the new one */
	aurade_seat->focused_surface = surface;
	if (shsurf->focus_count++ == 0)
		weston_desktop_surface_set_activated(dsurface, true);

	/* raise the focused subtree to the top of the visible layer */
	if (shoutput)
		aurade_shell_output_raise_surface_subtree(shoutput, shsurf);
}

/*
 * The pointer, in Ash's arrangement of the displays
 */

static const struct aurade_layout_entry *
aurade_shell_layout_for(struct aurade_shell *shell, struct weston_output *output)
{
	int i;

	if (!output->name)
		return NULL;
	for (i = 0; i < shell->layout_count; i++) {
		if (strcmp(shell->layout[i].name, output->name) == 0)
			return &shell->layout[i];
	}
	return NULL;
}

static struct weston_output *
aurade_shell_output_at(struct weston_compositor *compositor,
		       struct weston_coord_global pos)
{
	struct weston_output *output;

	wl_list_for_each(output, &compositor->output_list, link) {
		if (output->destroying)
			continue;
		if (weston_output_contains_coord(output, pos))
			return output;
	}
	return NULL;
}

static double
clamp_double(double value, double low, double high)
{
	if (value < low)
		return low;
	if (value > high)
		return high;
	return value;
}

/* Weston moves the pointer in its own pixels, with the outputs side by side.
 * When a relative motion would take the pointer off the output it is on,
 * redo it in Ash's logical pixels: find the display Ash has at the point
 * the motion ends, and put the pointer at the same place on that display's
 * output. Off the edge of Ash's desktop, it stays at the edge of the output
 * it was on. Returns false to leave the motion to weston. */
static bool
aurade_shell_map_motion(struct aurade_shell *shell,
			struct weston_pointer *pointer,
			const struct weston_pointer_motion_event *event,
			struct weston_pointer_motion_event *mapped)
{
	struct weston_coord_global to;
	struct weston_output *from_output, *output;
	const struct aurade_layout_entry *from_entry, *to_entry = NULL;
	struct weston_output *to_output = NULL;
	double lx, ly;

	if (shell->layout_count == 0)
		return false;
	/* Tablets and touch already land on the output they belong to. */
	if (!(event->mask & WESTON_POINTER_MOTION_REL) ||
	    (event->mask & WESTON_POINTER_MOTION_ABS))
		return false;

	from_output = aurade_shell_output_at(shell->compositor, pointer->pos);
	if (!from_output || from_output->width <= 0 || from_output->height <= 0)
		return false;

	to = pointer->pos;
	to.c.x += event->rel.x;
	to.c.y += event->rel.y;
	if (weston_output_contains_coord(from_output, to))
		return false;

	from_entry = aurade_shell_layout_for(shell, from_output);
	if (!from_entry || from_entry->width <= 0 || from_entry->height <= 0)
		return false;

	lx = from_entry->x + (to.c.x - from_output->pos.c.x) *
			     from_entry->width / from_output->width;
	ly = from_entry->y + (to.c.y - from_output->pos.c.y) *
			     from_entry->height / from_output->height;

	wl_list_for_each(output, &shell->compositor->output_list, link) {
		const struct aurade_layout_entry *entry;

		if (output == from_output || output->destroying ||
		    output->width <= 0 || output->height <= 0)
			continue;
		entry = aurade_shell_layout_for(shell, output);
		if (!entry || entry->width <= 0 || entry->height <= 0)
			continue;
		if (lx >= entry->x && lx < entry->x + entry->width &&
		    ly >= entry->y && ly < entry->y + entry->height) {
			to_output = output;
			to_entry = entry;
			break;
		}
	}

	*mapped = *event;
	mapped->mask |= WESTON_POINTER_MOTION_ABS;
	if (to_output) {
		mapped->abs.c.x = to_output->pos.c.x +
			(lx - to_entry->x) * to_output->width / to_entry->width;
		mapped->abs.c.y = to_output->pos.c.y +
			(ly - to_entry->y) * to_output->height / to_entry->height;
	} else {
		to_output = from_output;
		mapped->abs = to;
	}
	mapped->abs.c.x = clamp_double(mapped->abs.c.x, to_output->pos.c.x,
				       to_output->pos.c.x + to_output->width - 1);
	mapped->abs.c.y = clamp_double(mapped->abs.c.y, to_output->pos.c.y,
				       to_output->pos.c.y + to_output->height - 1);
	return true;
}

/* While a button is held, weston keeps the pointer's focus on the surface
 * the press went to. When the pointer goes on to a top-level surface of the
 * same client on another output, an Ash host window on another monitor,
 * hand the focus over, buttons still down, so the drag goes on there the way
 * it does when Ash owns the monitors itself. */
static bool
aurade_shell_hand_over_drag(struct weston_pointer *pointer)
{
	struct weston_view *view;
	struct weston_surface *from, *to;

	if (!pointer->focus)
		return false;

	view = weston_compositor_pick_view(pointer->seat->compositor,
					   pointer->pos);
	if (!view || view == pointer->focus ||
	    view->output == pointer->focus->output)
		return false;

	from = weston_surface_get_main_surface(pointer->focus->surface);
	to = weston_surface_get_main_surface(view->surface);
	if (from == to || !from->resource || !to->resource)
		return false;
	if (wl_resource_get_client(from->resource) !=
	    wl_resource_get_client(to->resource))
		return false;
	if (!get_aurade_shell_surface(from) || !get_aurade_shell_surface(to))
		return false;

	weston_pointer_set_focus(pointer, view);
	return true;
}

static void
aurade_pointer_grab_focus(struct weston_pointer_grab *grab)
{
	if (grab->pointer->button_count > 0 &&
	    aurade_shell_hand_over_drag(grab->pointer))
		return;
	the_shell->weston_grab->focus(grab);
}

static void
aurade_pointer_grab_motion(struct weston_pointer_grab *grab,
			   const struct timespec *time,
			   struct weston_pointer_motion_event *event)
{
	struct weston_pointer_motion_event mapped;

	if (aurade_shell_map_motion(the_shell, grab->pointer, event, &mapped))
		event = &mapped;
	the_shell->weston_grab->motion(grab, time, event);
}

static void
aurade_pointer_grab_button(struct weston_pointer_grab *grab,
			   const struct timespec *time,
			   uint32_t button, uint32_t state)
{
	the_shell->weston_grab->button(grab, time, button, state);
}

static void
aurade_pointer_grab_axis(struct weston_pointer_grab *grab,
			 const struct timespec *time,
			 struct weston_pointer_axis_event *event)
{
	the_shell->weston_grab->axis(grab, time, event);
}

static void
aurade_pointer_grab_axis_source(struct weston_pointer_grab *grab,
				uint32_t source)
{
	the_shell->weston_grab->axis_source(grab, source);
}

static void
aurade_pointer_grab_frame(struct weston_pointer_grab *grab)
{
	the_shell->weston_grab->frame(grab);
}

static void
aurade_pointer_grab_cancel(struct weston_pointer_grab *grab)
{
	the_shell->weston_grab->cancel(grab);
}

/* Takes the default pointer grab over once a pointer exists, since weston's
 * own grab can only be read from a pointer. */
static void
aurade_shell_install_pointer_grab(struct aurade_shell *shell,
				  struct weston_seat *seat)
{
	struct weston_pointer *pointer = weston_seat_get_pointer(seat);

	if (shell->pointer_grab_installed || !pointer)
		return;

	shell->weston_grab = pointer->default_grab.interface;
	shell->pointer_grab = (struct weston_pointer_grab_interface) {
		.focus = aurade_pointer_grab_focus,
		.motion = aurade_pointer_grab_motion,
		.button = aurade_pointer_grab_button,
		.axis = aurade_pointer_grab_axis,
		.axis_source = aurade_pointer_grab_axis_source,
		.frame = aurade_pointer_grab_frame,
		.cancel = aurade_pointer_grab_cancel,
	};
	shell->pointer_grab_installed = true;
	weston_compositor_set_default_pointer_grab(shell->compositor,
						   &shell->pointer_grab);
}

static void
aurade_shell_read_layout(struct aurade_shell *shell)
{
	char path[PATH_MAX];
	char line[256];
	FILE *file;
	int count = 0;

	if (!shell->layout_dir)
		return;
	snprintf(path, sizeof path, "%s/display-layout", shell->layout_dir);
	file = fopen(path, "re");
	if (!file) {
		shell->layout_count = 0;
		return;
	}
	while (count < AURADE_LAYOUT_MAX && fgets(line, sizeof line, file)) {
		struct aurade_layout_entry *entry = &shell->layout[count];

		if (sscanf(line, "%63s %lf %lf %lf %lf", entry->name,
			   &entry->x, &entry->y, &entry->width,
			   &entry->height) == 5 &&
		    entry->width > 0 && entry->height > 0)
			count++;
	}
	fclose(file);
	shell->layout_count = count;
	weston_log("aurade-shell: %d displays in Ash's arrangement\n", count);
}

static int
aurade_shell_handle_inotify(int fd, uint32_t mask, void *data)
{
	struct aurade_shell *shell = data;
	char buffer[4096]
		__attribute__ ((aligned(__alignof__(struct inotify_event))));
	bool reload = false;
	ssize_t length;

	while ((length = read(fd, buffer, sizeof buffer)) > 0) {
		char *p = buffer;

		while (p < buffer + length) {
			struct inotify_event *event = (struct inotify_event *) p;

			if (event->len &&
			    strcmp(event->name, "display-layout") == 0)
				reload = true;
			p += sizeof(struct inotify_event) + event->len;
		}
	}
	if (reload)
		aurade_shell_read_layout(shell);
	return 0;
}

static void
aurade_shell_watch_layout(struct aurade_shell *shell)
{
	const char *runtime_dir = getenv("XDG_RUNTIME_DIR");
	struct wl_event_loop *loop;
	size_t size;

	shell->inotify_fd = -1;
	if (!runtime_dir || !runtime_dir[0])
		return;

	size = strlen(runtime_dir) + sizeof("/aurade");
	shell->layout_dir = malloc(size);
	if (!shell->layout_dir)
		return;
	snprintf(shell->layout_dir, size, "%s/aurade", runtime_dir);
	if (mkdir(shell->layout_dir, 0700) < 0 && errno != EEXIST) {
		weston_log("aurade-shell: cannot make %s: %s\n",
			   shell->layout_dir, strerror(errno));
		return;
	}

	shell->inotify_fd = inotify_init1(IN_NONBLOCK | IN_CLOEXEC);
	if (shell->inotify_fd < 0)
		return;
	if (inotify_add_watch(shell->inotify_fd, shell->layout_dir,
			      IN_CLOSE_WRITE | IN_MOVED_TO) < 0) {
		close(shell->inotify_fd);
		shell->inotify_fd = -1;
		return;
	}
	loop = wl_display_get_event_loop(shell->compositor->wl_display);
	shell->inotify_source =
		wl_event_loop_add_fd(loop, shell->inotify_fd, WL_EVENT_READABLE,
				     aurade_shell_handle_inotify, shell);
	aurade_shell_read_layout(shell);
}

/*
 * aurade_shell_seat
 */

static void
aurade_shell_seat_destroy(struct aurade_shell_seat *shseat)
{
	wl_list_remove(&shseat->seat_destroy_listener.link);
	wl_list_remove(&shseat->caps_listener.link);
	wl_list_remove(&shseat->link);
	free(shseat);
}

static void
aurade_shell_seat_handle_destroy(struct wl_listener *listener, void *data)
{
	struct aurade_shell_seat *shseat =
		container_of(listener,
			     struct aurade_shell_seat, seat_destroy_listener);

	aurade_shell_seat_destroy(shseat);
}

static void
aurade_shell_seat_handle_caps(struct wl_listener *listener, void *data)
{
	struct weston_seat *seat = data;

	if (the_shell)
		aurade_shell_install_pointer_grab(the_shell, seat);
}

static struct aurade_shell_seat *
aurade_shell_seat_create(struct aurade_shell *shell, struct weston_seat *seat)
{
	struct aurade_shell_seat *shseat;

	if (wl_list_length(&shell->seat_list) > 0) {
		weston_log("WARNING: multiple seats detected. aurade-shell "
			   "can not handle multiple seats!\n");
		return NULL;
	}

	shseat = calloc(1, sizeof *shseat);
	if (!shseat) {
		weston_log("no memory to allocate shell seat\n");
		return NULL;
	}

	shseat->seat = seat;

	shseat->seat_destroy_listener.notify = aurade_shell_seat_handle_destroy;
	wl_signal_add(&seat->destroy_signal, &shseat->seat_destroy_listener);

	shseat->caps_listener.notify = aurade_shell_seat_handle_caps;
	wl_signal_add(&seat->updated_caps_signal, &shseat->caps_listener);

	wl_list_insert(&shell->seat_list, &shseat->link);

	aurade_shell_install_pointer_grab(shell, seat);

	return shseat;
}

/*
 * aurade_shell_output
 */

static void
aurade_shell_output_set_active_surface_tree(struct aurade_shell_output *shoutput,
					    struct aurade_shell_surface *shroot)
{
	struct aurade_shell *shell = shoutput->shell;
	struct aurade_shell_surface *s;

	/* Remove the previous active surface tree (i.e., move the tree to
	 * WESTON_LAYER_POSITION_HIDDEN) */
	if (shoutput->active_surface_tree) {
		wl_list_for_each_reverse(s, shoutput->active_surface_tree,
					 surface_tree_link) {
			weston_view_move_to_layer(s->view,
						  &shell->inactive_layer.view_list);
		}
	}

	if (shroot) {
		wl_list_for_each_reverse(s, &shroot->surface_tree_list,
					 surface_tree_link) {
			weston_view_move_to_layer(s->view,
						  &shell->normal_layer.view_list);
		}
	}

	shoutput->active_surface_tree = shroot ?
					&shroot->surface_tree_list :
					NULL;
}

/* Raises the subtree originating at the specified 'shroot' of the output's
 * active surface tree to the top of the visible layer. */
static void
aurade_shell_output_raise_surface_subtree(struct aurade_shell_output *shoutput,
					  struct aurade_shell_surface *shroot)
{
	struct aurade_shell *shell = shroot->shell;
	struct wl_list tmp_list;
	struct aurade_shell_surface *s, *tmp_s;

	wl_list_init(&tmp_list);

	if (!shoutput->active_surface_tree)
		return;

	/* Move all shell surfaces in the active surface tree starting at
	 * shroot to the tmp_list while maintaining the relative order. */
	wl_list_for_each_reverse_safe(s, tmp_s,
				      shoutput->active_surface_tree,
				      surface_tree_link) {
		if (aurade_shell_surface_is_descendant_of(s, shroot)) {
			active_surface_tree_move_element_to_top(&tmp_list,
								&s->surface_tree_link);
		}
	}

	/* Now insert the views corresponding to the shell surfaces stored to
	 * the top of the layer in the proper order.
	 * Also remove the shell surface from tmp_list and insert it at the top
	 * of the output's active surface tree. */
	wl_list_for_each_reverse_safe(s, tmp_s, &tmp_list, surface_tree_link) {
		weston_view_move_to_layer(s->view,
					  &shell->normal_layer.view_list);

		active_surface_tree_move_element_to_top(shoutput->active_surface_tree,
							&s->surface_tree_link);
	}
}

static int
aurade_shell_background_surface_get_label(struct weston_surface *surface,
					  char *buf, size_t len)
{
	return snprintf(buf, len, "aurade shell background surface");
}

static void
aurade_shell_output_recreate_background(struct aurade_shell_output *shoutput)
{
	struct aurade_shell *shell = shoutput->shell;
	struct weston_compositor *ec = shell->compositor;
	struct weston_output *output = shoutput->output;
	struct weston_config_section *shell_section = NULL;
	uint32_t bg_color = 0x0;
	struct weston_curtain_params curtain_params = {};

	if (shoutput->curtain)
		weston_shell_utils_curtain_destroy(shoutput->curtain);
	shoutput->curtain = NULL;

	if (!output)
		return;

	if (shell->config)
		shell_section = weston_config_get_section(shell->config,
							  "shell", NULL, NULL);
	if (shell_section)
		weston_config_section_get_color(shell_section, "background-color",
						&bg_color, 0x00000000);

	curtain_params.r = ((bg_color >> 16) & 0xff) / 255.0;
	curtain_params.g = ((bg_color >> 8) & 0xff) / 255.0;
	curtain_params.b = ((bg_color >> 0) & 0xff) / 255.0;
	curtain_params.a = 1.0;

	curtain_params.pos = output->pos;
	curtain_params.width = output->width;
	curtain_params.height = output->height;

	curtain_params.capture_input = true;

	curtain_params.get_label = aurade_shell_background_surface_get_label;
	curtain_params.surface_committed = NULL;
	curtain_params.surface_private = NULL;

	shoutput->curtain = weston_shell_utils_curtain_create(ec, &curtain_params);

	weston_surface_set_role(shoutput->curtain->view->surface,
				"aurade-shell-background", NULL, 0);

	shoutput->curtain->view->surface->output = output;

	weston_view_move_to_layer(shoutput->curtain->view,
				  &shell->background_layer.view_list);
	weston_view_set_output(shoutput->curtain->view, output);
}

static void
aurade_shell_output_stop_watchdog(struct aurade_shell_output *shoutput)
{
	wl_list_remove(&shoutput->first_latch_listener.link);
	wl_list_init(&shoutput->first_latch_listener.link);
	if (shoutput->start_watchdog) {
		wl_event_source_remove(shoutput->start_watchdog);
		shoutput->start_watchdog = NULL;
	}
}

static void
aurade_shell_output_first_latch(struct wl_listener *listener, void *data)
{
	struct aurade_shell_output *shoutput =
		container_of(listener, struct aurade_shell_output,
			     first_latch_listener);

	aurade_shell_output_stop_watchdog(shoutput);
}

/* A monitor plugged in while another one is mid-frame can stay dark.
 * The hotplug makes weston's DRM backend recover its whole state once the
 * frames in flight finish, and a new output whose repaint loop starts
 * during that wait is told it will be part of the recovery, but the
 * recovery only commits outputs that repaint, and this one waits for a
 * completion that never comes. Weston 15.0.1 and its main branch both do
 * this. An output that has never latched a frame has nothing in flight,
 * since only its own repaint could have committed anything for it, so its
 * repaint loop is safe to restart, and is restarted until it paints. */
static int
aurade_shell_output_start_watchdog(void *data)
{
	struct aurade_shell_output *shoutput = data;
	struct weston_output *output = shoutput->output;

	if (output->repaint_status == REPAINT_AWAITING_COMPLETION) {
		weston_log("aurade-shell: output %s has not started painting, "
			   "restarting its repaint loop\n", output->name);
		weston_output_schedule_repaint_reset(output);
		weston_output_schedule_repaint(output);
	}

	if (++shoutput->start_watchdog_ticks < 50)
		wl_event_source_timer_update(shoutput->start_watchdog, 100);
	else
		aurade_shell_output_stop_watchdog(shoutput);
	return 0;
}

static void
aurade_shell_output_destroy(struct aurade_shell_output *shoutput)
{
	aurade_shell_output_stop_watchdog(shoutput);

	shoutput->output = NULL;
	shoutput->output_destroy_listener.notify = NULL;

	if (shoutput->curtain)
		weston_shell_utils_curtain_destroy(shoutput->curtain);

	wl_list_remove(&shoutput->output_destroy_listener.link);
	wl_list_remove(&shoutput->link);

	free(shoutput);
}

static void
aurade_shell_output_notify_output_destroy(struct wl_listener *listener,
					  void *data)
{
	struct aurade_shell_output *shoutput =
		container_of(listener,
			     struct aurade_shell_output, output_destroy_listener);

	aurade_shell_output_destroy(shoutput);
}

static struct aurade_shell_output *
aurade_shell_output_create(struct aurade_shell *shell,
			   struct weston_output *output)
{
	struct aurade_shell_output *shoutput;

	shoutput = calloc(1, sizeof *shoutput);
	if (shoutput == NULL)
		return NULL;

	shoutput->output = output;
	shoutput->shell = shell;

	shoutput->output_destroy_listener.notify =
		aurade_shell_output_notify_output_destroy;
	wl_signal_add(&shoutput->output->destroy_signal,
		      &shoutput->output_destroy_listener);

	wl_list_insert(shell->output_list.prev, &shoutput->link);

	weston_output_set_shell_private(output, shoutput);

	shoutput->first_latch_listener.notify = aurade_shell_output_first_latch;
	wl_signal_add(&output->post_latch_signal,
		      &shoutput->first_latch_listener);
	shoutput->start_watchdog =
		wl_event_loop_add_timer(
			wl_display_get_event_loop(shell->compositor->wl_display),
			aurade_shell_output_start_watchdog, shoutput);
	if (shoutput->start_watchdog)
		wl_event_source_timer_update(shoutput->start_watchdog, 100);

	aurade_shell_output_recreate_background(shoutput);
	weston_output_set_ready(output);

	return shoutput;
}

/*
 * libweston-desktop
 */

static void
desktop_surface_added(struct weston_desktop_surface *desktop_surface,
		      void *data)
{
	struct aurade_shell *shell = data;
	struct aurade_shell_surface *shsurf;
	struct weston_surface *surface =
		weston_desktop_surface_get_surface(desktop_surface);

	shsurf = aurade_shell_surface_create(shell, desktop_surface);
	if (!shsurf)
		return;

	weston_surface_set_label_func(surface,
				      weston_shell_utils_surface_get_label);
	aurade_shell_surface_set_fullscreen(shsurf, NULL);
}

/* Return the shell surface that should gain focus after the specified shsurf
 * is destroyed. We prefer the top remaining view from the same parent
 * surface, but if we can't find one we fall back to the top view regardless
 * of parentage. First look for the successor in the normal layer, and if
 * that fails, look for it in the inactive layer, and if that also fails, then
 * there is no successor. */
static struct aurade_shell_surface *
find_focus_successor(struct aurade_shell_surface *shsurf,
		     struct weston_surface *focused_surface)
{
	struct aurade_shell_surface *parent_root =
		aurade_shell_surface_get_parent_root(shsurf);
	struct weston_view *top_view = NULL;
	struct aurade_shell_surface *successor = NULL;
	struct wl_list *layers = &shsurf->shell->compositor->layer_list;
	struct weston_layer *layer;
	struct weston_view *view;

	if (!shsurf->output)
		return NULL;

	wl_list_for_each(layer, layers, link) {
		struct aurade_shell *shell = shsurf->shell;

		if (layer != &shell->inactive_layer &&
		    layer != &shell->normal_layer) {
			continue;
		}
		wl_list_for_each(view, &layer->view_list.link, layer_link.link) {
			struct aurade_shell_surface *view_shsurf;
			struct aurade_shell_surface *root;

			if (view == shsurf->view)
				continue;

			/* pick views only on the same output */
			if (view->output != shsurf->output->output)
				continue;

			view_shsurf = get_aurade_shell_surface(view->surface);
			if (!view_shsurf)
				continue;

			if (!top_view)
				top_view = view;

			root = aurade_shell_surface_get_parent_root(view_shsurf);
			if (root == parent_root) {
				top_view = view;
				break;
			}
		}
	}

	if (top_view)
		successor = get_aurade_shell_surface(top_view->surface);

	return successor;
}

static void
desktop_surface_removed(struct weston_desktop_surface *desktop_surface,
			void *data)
{
	struct aurade_shell *shell = data;
	struct aurade_shell_surface *shsurf =
		weston_desktop_surface_get_user_data(desktop_surface);
	struct weston_surface *surface =
		weston_desktop_surface_get_surface(desktop_surface);
	struct weston_seat *seat;
	struct aurade_shell_seat *aurade_seat;
	struct aurade_shell_output *shoutput;

	if (!shsurf)
		return;

	seat = get_aurade_shell_first_seat(shell);
	aurade_seat = get_aurade_shell_seat(seat);
	shoutput = shsurf->output;

	/* Inform children about destruction of their parent, so that we can
	 * reparent them and potentially relink surface tree links before
	 * finding a focus successor and activating a new surface. */
	wl_signal_emit(&shsurf->parent_destroy_signal, shsurf);

	/* We need to take into account that the surface being destroyed it not
	 * always the same as the focused surface, which could result in picking
	 * and *activating* the wrong window.
	 *
	 * Apply that only on the same output to avoid incorrectly picking an
	 * invalid surface, which could happen if the view being destroyed
	 * is on a output different than the focused_surface output */
	if (seat && aurade_seat && aurade_seat->focused_surface &&
	    (aurade_seat->focused_surface == surface ||
	    surface->output != aurade_seat->focused_surface->output)) {
		struct aurade_shell_surface *successor;

		successor = find_focus_successor(shsurf,
						 aurade_seat->focused_surface);
		if (shoutput && successor) {
			enum weston_layer_position succesor_view_layer_pos;

			succesor_view_layer_pos =
				weston_shell_utils_view_get_layer_position(successor->view);
			if (succesor_view_layer_pos == WESTON_LAYER_POSITION_HIDDEN) {
				struct aurade_shell_surface *shroot =
					aurade_shell_surface_get_parent_root(successor);

				aurade_shell_output_set_active_surface_tree(shoutput,
									    shroot);
			}
			aurade_shell_surface_activate(successor, aurade_seat,
						      WESTON_ACTIVATE_FLAG_NONE);
		} else {
			if (aurade_seat->focused_surface == surface)
				aurade_seat->focused_surface = NULL;
			if (shoutput &&
			    shoutput->active_surface_tree == &shsurf->surface_tree_list)
				aurade_shell_output_set_active_surface_tree(shoutput,
									    NULL);
		}
	} else if (shoutput && !shsurf->parent &&
		   shoutput->active_surface_tree == &shsurf->surface_tree_list) {
		/* Not the focused surface: its output still has to stop
		 * pointing at a tree that is going away. */
		struct aurade_shell_surface *other =
			aurade_shell_output_find_other_root(shoutput, shsurf);

		shoutput->active_surface_tree = NULL;
		aurade_shell_output_set_active_surface_tree(shoutput, other);
	}

	aurade_shell_surface_destroy(shsurf);
}

static void
desktop_surface_committed(struct weston_desktop_surface *desktop_surface,
			  struct weston_coord_surface buf_offset, void *data)
{
	struct aurade_shell_surface *shsurf =
		weston_desktop_surface_get_user_data(desktop_surface);
	struct weston_surface *surface =
		weston_desktop_surface_get_surface(desktop_surface);
	bool is_resized;
	bool is_fullscreen;

	assert(shsurf);

	if (surface->width == 0)
		return;

	/* A surface whose output went away goes somewhere that still exists. */
	if (!shsurf->output) {
		struct aurade_shell_output *shoutput =
			aurade_shell_surface_find_best_output(shsurf);

		if (!shoutput)
			return;
		if (!shsurf->parent)
			aurade_shell_surface_move_to_output(shsurf, shoutput);
		else
			aurade_shell_surface_set_output(shsurf, shoutput);
		aurade_shell_surface_reconfigure_for_output(shsurf);
	}

	is_resized = surface->width != shsurf->last_width ||
		     surface->height != shsurf->last_height;
	is_fullscreen = weston_desktop_surface_get_maximized(desktop_surface) ||
			weston_desktop_surface_get_fullscreen(desktop_surface);

	if (!weston_surface_is_mapped(surface) || (is_resized && is_fullscreen)) {
		weston_shell_utils_center_on_output(shsurf->view,
						    shsurf->output->output);
		weston_view_update_transform(shsurf->view);
	}

	if (!weston_surface_is_mapped(surface)) {
		struct weston_seat *seat =
			get_aurade_shell_first_seat(shsurf->shell);
		struct aurade_shell_output *shoutput = shsurf->output;
		struct aurade_shell_seat *aurade_seat;

		weston_surface_map(surface);

		aurade_seat = get_aurade_shell_seat(seat);

		/* We are mapping a new surface tree root; set it active,
		 * replacing the previous one */
		if (!shsurf->parent) {
			aurade_shell_output_set_active_surface_tree(shoutput,
								    shsurf);
		}

		if (seat && aurade_seat)
			aurade_shell_surface_activate(shsurf, aurade_seat,
						      WESTON_ACTIVATE_FLAG_NONE);
	}

	if (!is_fullscreen && (buf_offset.c.x != 0 || buf_offset.c.y != 0)) {
		struct weston_coord_global pos;

		pos = weston_view_get_pos_offset_global(shsurf->view);
		weston_view_set_position_with_offset(shsurf->view,
						     pos, buf_offset);
		weston_view_update_transform(shsurf->view);
	}

	shsurf->last_width = surface->width;
	shsurf->last_height = surface->height;
}

static void
desktop_surface_move(struct weston_desktop_surface *desktop_surface,
		     struct weston_seat *seat, uint32_t serial, void *shell)
{
}

static void
desktop_surface_resize(struct weston_desktop_surface *desktop_surface,
		       struct weston_seat *seat, uint32_t serial,
		       enum weston_desktop_surface_edge edges, void *shell)
{
}

static void
desktop_surface_set_parent(struct weston_desktop_surface *desktop_surface,
			   struct weston_desktop_surface *parent,
			   void *shell)
{
	struct aurade_shell_surface *shsurf =
		weston_desktop_surface_get_user_data(desktop_surface);
	struct aurade_shell_surface *shsurf_parent =
		parent ? weston_desktop_surface_get_user_data(parent) : NULL;

	aurade_shell_surface_set_parent(shsurf, shsurf_parent);
}

static void
desktop_surface_fullscreen_requested(struct weston_desktop_surface *desktop_surface,
				     bool fullscreen,
				     struct weston_output *output, void *shell)
{
	struct aurade_shell_surface *shsurf =
		weston_desktop_surface_get_user_data(desktop_surface);
	struct aurade_shell_output *shoutput = NULL;

	if (output)
		shoutput = weston_output_get_shell_private(output);

	/* Top-level surfaces are always fullscreen. A request that names an
	 * output moves the surface there. */
	if (!shsurf->parent || fullscreen)
		aurade_shell_surface_set_fullscreen(shsurf, shoutput);
	else
		aurade_shell_surface_set_normal(shsurf);
}

static void
desktop_surface_maximized_requested(struct weston_desktop_surface *desktop_surface,
				    bool maximized, void *shell)
{
	struct aurade_shell_surface *shsurf =
		weston_desktop_surface_get_user_data(desktop_surface);

	if (!shsurf->parent)
		aurade_shell_surface_set_fullscreen(shsurf, NULL);
	else if (maximized) {
		weston_desktop_surface_set_maximized(shsurf->desktop_surface, true);
		if (shsurf->output)
			weston_desktop_surface_set_size(shsurf->desktop_surface,
							shsurf->output->output->width,
							shsurf->output->output->height);
	} else
		aurade_shell_surface_set_normal(shsurf);
}

static void
desktop_surface_minimized_requested(struct weston_desktop_surface *desktop_surface,
				    void *shell)
{
}

static void
desktop_surface_ping_timeout(struct weston_desktop_client *desktop_client,
			     void *shell_)
{
}

static void
desktop_surface_pong(struct weston_desktop_client *desktop_client,
		     void *shell_)
{
}

static void
desktop_surface_get_position(struct weston_desktop_surface *desktop_surface,
			     int32_t *x, int32_t *y, void *shell)
{
	struct aurade_shell_surface *shsurf =
		weston_desktop_surface_get_user_data(desktop_surface);

	*x = shsurf->view->geometry.pos_offset.x;
	*y = shsurf->view->geometry.pos_offset.y;
}

static const struct weston_desktop_api aurade_shell_desktop_api = {
	.struct_size = sizeof(struct weston_desktop_api),
	.surface_added = desktop_surface_added,
	.surface_removed = desktop_surface_removed,
	.committed = desktop_surface_committed,
	.move = desktop_surface_move,
	.resize = desktop_surface_resize,
	.set_parent = desktop_surface_set_parent,
	.fullscreen_requested = desktop_surface_fullscreen_requested,
	.maximized_requested = desktop_surface_maximized_requested,
	.minimized_requested = desktop_surface_minimized_requested,
	.ping_timeout = desktop_surface_ping_timeout,
	.pong = desktop_surface_pong,
	.get_position = desktop_surface_get_position,
};

/*
 * aurade_shell
 */

static void
aurade_shell_activate_view(struct aurade_shell *shell,
			   struct weston_view *view,
			   struct weston_seat *seat,
			   uint32_t flags)
{
	struct weston_surface *main_surface =
		weston_surface_get_main_surface(view->surface);
	struct aurade_shell_surface *shsurf =
		get_aurade_shell_surface(main_surface);
	struct aurade_shell_seat *aurade_seat =
		get_aurade_shell_seat(seat);

	if (!shsurf || !aurade_seat)
		return;

	aurade_shell_surface_activate(shsurf, aurade_seat, flags);
}

static void
aurade_shell_click_to_activate_binding(struct weston_pointer *pointer,
				       const struct timespec *time,
				       uint32_t button, void *data)
{
	struct aurade_shell *shell = data;

	if (pointer->grab != &pointer->default_grab)
		return;
	if (pointer->focus == NULL)
		return;

	aurade_shell_activate_view(shell, pointer->focus, pointer->seat,
				   WESTON_ACTIVATE_FLAG_CLICKED);
}

static void
aurade_shell_touch_to_activate_binding(struct weston_touch *touch,
				       const struct timespec *time,
				       void *data)
{
	struct aurade_shell *shell = data;

	if (touch->grab != &touch->default_grab)
		return;
	if (touch->focus == NULL)
		return;

	aurade_shell_activate_view(shell, touch->focus, touch->seat,
				   WESTON_ACTIVATE_FLAG_NONE);
}

static void
aurade_shell_add_bindings(struct aurade_shell *shell)
{
	uint32_t mod = 0;

	mod = weston_config_get_binding_modifier(shell->config, MODIFIER_SUPER);

	weston_compositor_add_button_binding(shell->compositor, BTN_LEFT, 0,
					     aurade_shell_click_to_activate_binding,
					     shell);
	weston_compositor_add_button_binding(shell->compositor, BTN_RIGHT, 0,
					     aurade_shell_click_to_activate_binding,
					     shell);
	weston_compositor_add_touch_binding(shell->compositor, 0,
					    aurade_shell_touch_to_activate_binding,
					    shell);

	weston_install_debug_key_binding(shell->compositor, mod);
}

static void
aurade_shell_handle_output_created(struct wl_listener *listener, void *data)
{
	struct aurade_shell *shell =
		container_of(listener, struct aurade_shell, output_created_listener);
	struct weston_output *output = data;

	aurade_shell_output_create(shell, output);
}

static void
aurade_shell_handle_output_resized(struct wl_listener *listener, void *data)
{
	struct aurade_shell *shell =
		container_of(listener, struct aurade_shell, output_resized_listener);
	struct weston_output *output = data;
	struct aurade_shell_output *shoutput =
		weston_output_get_shell_private(output);
	struct weston_view *view;

	aurade_shell_output_recreate_background(shoutput);

	wl_list_for_each(view, &shell->normal_layer.view_list.link,
			 layer_link.link) {
		struct aurade_shell_surface *shsurf;
		if (view->output != output)
			continue;
		shsurf = get_aurade_shell_surface(view->surface);
		if (!shsurf)
			continue;
		aurade_shell_surface_reconfigure_for_output(shsurf);
	}
}

static void
aurade_shell_handle_output_moved(struct wl_listener *listener, void *data)
{
	struct aurade_shell *shell =
		container_of(listener, struct aurade_shell, output_moved_listener);
	struct weston_output *output = data;
	struct weston_view *view;

	wl_list_for_each(view, &shell->background_layer.view_list.link,
			 layer_link.link) {
		struct weston_coord_global pos;

		if (view->output != output)
			continue;

		pos = weston_coord_global_add(
		      weston_view_get_pos_offset_global(view),
		      output->move);
		weston_view_set_position(view, pos);
	}

	wl_list_for_each(view, &shell->normal_layer.view_list.link,
			 layer_link.link) {
		struct weston_coord_global pos;

		if (view->output != output)
			continue;

		pos = weston_coord_global_add(
		      weston_view_get_pos_offset_global(view),
		      output->move);
		weston_view_set_position(view, pos);
	}
}

static void
aurade_shell_handle_seat_created(struct wl_listener *listener, void *data)
{
	struct weston_seat *seat = data;
	struct aurade_shell *shell =
		container_of(listener, struct aurade_shell, seat_created_listener);
	aurade_shell_seat_create(shell, seat);
}

static void
aurade_shell_destroy_surfaces_on_layer(struct weston_layer *layer)
{
	struct weston_view *view, *view_next;

	wl_list_for_each_safe(view, view_next, &layer->view_list.link,
			      layer_link.link) {
		struct aurade_shell_surface *shsurf =
			get_aurade_shell_surface(view->surface);
		assert(shsurf);
		aurade_shell_surface_destroy(shsurf);
	}

	weston_layer_fini(layer);
}

static void
aurade_shell_destroy(struct wl_listener *listener, void *data)
{
	struct aurade_shell *shell =
		container_of(listener, struct aurade_shell, destroy_listener);
	struct aurade_shell_output *shoutput, *tmp;
	struct aurade_shell_seat *shseat, *shseat_next;

	wl_list_remove(&shell->destroy_listener.link);
	wl_list_remove(&shell->output_created_listener.link);
	wl_list_remove(&shell->output_resized_listener.link);
	wl_list_remove(&shell->output_moved_listener.link);
	wl_list_remove(&shell->seat_created_listener.link);
	wl_list_remove(&shell->session_listener.link);

	if (shell->pointer_grab_installed)
		weston_compositor_set_default_pointer_grab(shell->compositor,
							   NULL);
	if (shell->inotify_source)
		wl_event_source_remove(shell->inotify_source);
	if (shell->inotify_fd >= 0)
		close(shell->inotify_fd);
	free(shell->layout_dir);

	wl_list_for_each_safe(shoutput, tmp, &shell->output_list, link) {
		aurade_shell_output_destroy(shoutput);
	}

	/* bg layer doesn't contain a weston_desktop_surface, and
	 * aurade_shell_output_destroy() takes care of destroying it, we're just
	 * doing a weston_layer_fini() here as there might be multiple bg
	 * views */
	weston_layer_fini(&shell->background_layer);
	aurade_shell_destroy_surfaces_on_layer(&shell->normal_layer);
	aurade_shell_destroy_surfaces_on_layer(&shell->inactive_layer);

	wl_list_for_each_safe(shseat, shseat_next, &shell->seat_list, link) {
		aurade_shell_seat_destroy(shseat);
	}

	weston_desktop_destroy(shell->desktop);

	if (shell->config)
		weston_config_destroy(shell->config);
	the_shell = NULL;
	free(shell);
}

static void
aurade_shell_notify_session(struct wl_listener *listener, void *data)
{
	struct aurade_shell *shell =
		container_of(listener, struct aurade_shell, session_listener);
	struct aurade_shell_seat *a_seat;
	struct weston_compositor *compositor = data;
	struct weston_seat *seat = get_aurade_shell_first_seat(shell);

	if (!compositor->session_active || !seat)
		return;

	a_seat = get_aurade_shell_seat(seat);
	if (a_seat && a_seat->focused_surface) {
		struct aurade_shell_surface *current_focus =
			get_aurade_shell_surface(a_seat->focused_surface);

		weston_view_activate_input(current_focus->view,
					   a_seat->seat,
					   WESTON_ACTIVATE_FLAG_NONE);
	}
}

WL_EXPORT int
wet_shell_init(struct weston_compositor *ec,
	       int *argc, char *argv[])
{
	struct aurade_shell *shell;
	struct weston_seat *seat;
	struct weston_output *output;
	const char *config_file;

	shell = calloc(1, sizeof *shell);
	if (shell == NULL)
		return -1;

	shell->compositor = ec;
	shell->inotify_fd = -1;

	if (!weston_compositor_add_destroy_listener_once(ec,
							 &shell->destroy_listener,
							 aurade_shell_destroy)) {
		free(shell);
		return 0;
	}
	the_shell = shell;

	config_file = weston_config_get_name_from_env();
	shell->config = weston_config_parse(config_file);

	weston_layer_init(&shell->background_layer, ec);
	weston_layer_init(&shell->normal_layer, ec);
	weston_layer_init(&shell->inactive_layer, ec);

	weston_layer_set_position(&shell->background_layer,
				  WESTON_LAYER_POSITION_BACKGROUND);
	weston_layer_set_position(&shell->inactive_layer,
				  WESTON_LAYER_POSITION_HIDDEN);
	weston_layer_set_position(&shell->normal_layer,
				  WESTON_LAYER_POSITION_NORMAL);

	shell->desktop = weston_desktop_create(ec, &aurade_shell_desktop_api,
					       shell);
	if (!shell->desktop)
		return -1;

	wl_list_init(&shell->seat_list);
	wl_list_for_each(seat, &ec->seat_list, link)
		aurade_shell_seat_create(shell, seat);
	shell->seat_created_listener.notify = aurade_shell_handle_seat_created;
	wl_signal_add(&ec->seat_created_signal, &shell->seat_created_listener);

	wl_list_init(&shell->output_list);
	wl_list_for_each(output, &ec->output_list, link)
		aurade_shell_output_create(shell, output);

	shell->output_created_listener.notify = aurade_shell_handle_output_created;
	wl_signal_add(&ec->output_created_signal, &shell->output_created_listener);

	shell->output_resized_listener.notify = aurade_shell_handle_output_resized;
	wl_signal_add(&ec->output_resized_signal, &shell->output_resized_listener);

	shell->output_moved_listener.notify = aurade_shell_handle_output_moved;
	wl_signal_add(&ec->output_moved_signal, &shell->output_moved_listener);

	shell->session_listener.notify = aurade_shell_notify_session;
	wl_signal_add(&ec->session_signal, &shell->session_listener);
	screenshooter_create(ec);

	aurade_shell_add_bindings(shell);
	aurade_shell_watch_layout(shell);

	return 0;
}
