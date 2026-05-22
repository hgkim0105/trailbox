// Minimal client-side enhancement: confirm-by-default for danger buttons that
// don't carry an explicit onsubmit handler. No framework, no build step.
document.addEventListener('submit', function (ev) {
  var form = ev.target;
  if (!(form instanceof HTMLFormElement)) return;
  if (form.dataset.confirmed === '1') return;
  if (form.getAttribute('onsubmit')) return;  // explicit handler wins
  var btn = form.querySelector('button.danger');
  if (!btn) return;
  if (!window.confirm('정말 진행하시겠습니까?')) {
    ev.preventDefault();
  } else {
    form.dataset.confirmed = '1';
  }
});
