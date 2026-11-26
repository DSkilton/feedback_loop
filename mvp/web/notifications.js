/* Permission-based desktop notifications and the durable per-account inbox. */
(() => {
  let account = null, generation = 0, timer = null, lastSeen = null, busy = false;
  let current = null;
  const supported = () => "Notification" in window && window.isSecureContext;
  function stop() {
    clearInterval(timer);
    timer = null;
    account = null;
    lastSeen = null;
    current = null;
    busy = false;
    generation += 1;
    if ($("notificationCount")) $("notificationCount").textContent = "";
  }
  function activate() {
    const id = state.bootstrap?.user.id;
    if (!id || id === account) return;
    stop();
    account = id;
    poll();
    timer = setInterval(poll, 15000);
  }
  async function poll() {
    if (!account || busy) return;
    const token = generation;
    busy = true;
    try {
      const data = await api("/api/notifications");
      if (token !== generation) return;
      const changed = JSON.stringify(data) !== JSON.stringify(current);
      accept(data, true);
      const form = $("notificationPreferences");
      if (state.page === "notifications" && changed && !form?.dataset.dirty && !form?.contains(document.activeElement)) renderContents(data);
    } catch (_) {
      // A failed poll leaves the previous count visible. Inbox requests remain retryable.
    } finally {
      if (token === generation) busy = false;
    }
  }
  function accept(data, allowDesktop) {
    current = data;
    $("notificationCount").textContent = data.unread_count ? "(" + data.unread_count + ")" : "";
    const max = Math.max(0, ...data.items.map(n => n.id));
    if (lastSeen !== null && allowDesktop && data.preferences.desktop_enabled && supported() &&
        Notification.permission === "granted" && data.items.some(n => !n.read && n.id > lastSeen)) {
      try {
        const notice = new Notification("Feedback Loop", {
          body: "You have new notifications. Open Feedback Loop to view them.",
          tag: "feedback-loop-" + account,
        });
        const target = account;
        notice.onclick = () => {
          window.focus();
          if (account === target) $("notificationsNav").click();
          notice.close();
        };
      } catch (_) {
        // Desktop delivery is best effort; the durable inbox is authoritative.
      }
    }
    lastSeen = Math.max(lastSeen || 0, max);
  }
  async function render() {
    const id = state.bootstrap?.user.id;
    const data = await api("/api/notifications");
    if (state.page !== "notifications" || state.bootstrap?.user.id !== id) return;
    accept(data, false);
    renderContents(data);
  }
  function renderContents(data) {
    if (state.page !== "notifications") return;
    const esc = escapeHtml;
    $("app").innerHTML = '<section class="page-heading"><div><div class="eyebrow">COMMUNICATION</div><h1>Notifications</h1><p>Feedback, review requests and reminders.</p></div><span class="pale-pill">' +
      data.unread_count + ' unread</span></section><section class="report-panel"><h2>Preferences</h2><p class="quiet">Desktop alerts are optional and work while this app is open. Teams desktop delivery is not connected yet.</p>' +
      '<form id="notificationPreferences" class="feedback-form"><label class="tick-row"><input name="desktop_enabled" type="checkbox"' + (data.preferences.desktop_enabled ? ' checked' : '') + (supported() ? '' : ' disabled') + '> Desktop pop-ups on this device when permitted</label>' +
      '<label class="tick-row"><input name="review_reminders" type="checkbox"' + (data.preferences.review_reminders ? ' checked' : '') + '> Review reminders</label><button class="button-primary" type="submit">Save preferences</button></form></section>' +
      '<section class="report-panel"><div class="panel-heading"><h2>Inbox</h2><button type="button" class="button-ghost" id="notificationReadAll">Mark all read</button></div>' +
      (data.items.length ? '<div class="information-list">' + data.items.map(n => '<article class="feedback-card"><span class="tag tag-neutral">' + (n.read ? 'Read' : 'Unread') +
        '</span><p>' + esc(n.message) + '</p><small>' + esc(niceDate(n.created_at)) + '</small><button class="text-button" type="button" data-notification-id="' + n.id + '" data-feedback-id="' + n.feedback_id + '">Open feedback →</button></article>').join("") +
        '</div>' : '<p class="quiet">No notifications yet.</p>') + '</section>';
    const id = state.bootstrap.user.id;
    const sameAccount = () => state.bootstrap?.user.id === id && state.page === "notifications";
    $("notificationPreferences").addEventListener("change", event => { event.currentTarget.dataset.dirty = "true"; });
    $("notificationPreferences").addEventListener("submit", async event => {
      event.preventDefault();
      const form = event.currentTarget;
      let desktop = form.desktop_enabled.checked && supported();
      try {
        if (desktop && Notification.permission !== "granted") {
          desktop = await Notification.requestPermission() === "granted";
        }
        if (!sameAccount()) return;
        await api("/api/notifications/preferences", { method: "PUT", body: JSON.stringify({
          desktop_enabled: desktop, review_reminders: form.review_reminders.checked,
        }) });
        if (sameAccount()) { notify("Notification preferences saved"); await render(); }
      } catch (error) { if (sameAccount()) notify(error.message); }
    });
    $("notificationReadAll").addEventListener("click", async () => {
      try {
        await api("/api/notifications/read-all", { method: "POST" });
        if (sameAccount()) await render();
      } catch (error) { if (sameAccount()) notify(error.message); }
    });
    $("app").querySelectorAll("[data-notification-id]").forEach(button => button.addEventListener("click", async () => {
      try {
        await openThread(button.dataset.feedbackId);
        if (!sameAccount()) return;
        await api("/api/notifications/" + button.dataset.notificationId + "/read", { method: "POST" });
        if (sameAccount()) await render();
      } catch (error) { if (sameAccount()) notify(error.message); }
    }));
  }
  window.notifications = { activate, stop, render };
})();
