(function () {
  const app = document.getElementById('app');
  const MENU = JSON.parse(app.dataset.menu);
  const $ = (id) => document.getElementById(id);
  const peso = (n) => '₱' + Number(n).toLocaleString('en-PH');

  const state = {
    flavor: MENU.length ? MENU[0].name : null,
    size: 8,
    spicy: false,
    pack: 'Plastic',
    pay: 'Cash',
    paid: true,
    cart: [],
    saving: false,
  };

  function el(tag, props, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (k === 'class') n.className = v;
      else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v);
    }
    kids.flat().forEach((c) => n.append(c));
    return n;
  }

  const priceOf = (m) => (state.size === 4 ? m.p4 : m.p8);

  function syncSeg(groupId, value) {
    $(groupId).querySelectorAll('.seg').forEach((b) => {
      b.setAttribute('aria-pressed', String(b.dataset.value === String(value)));
    });
  }

  function bindSeg(groupId, key, parse) {
    $(groupId).addEventListener('click', (e) => {
      const b = e.target.closest('.seg');
      if (!b) return;
      state[key] = parse ? parse(b.dataset.value) : b.dataset.value;
      render();
    });
  }

  function renderFlavors() {
    const box = $('flavors');
    box.replaceChildren();
    if (!MENU.length) {
      box.append(el('p', { class: 'muted' }, 'Walang aktibong flavor. Idagdag sa Menu.'));
      return;
    }
    MENU.forEach((m) => {
      const on = state.flavor === m.name;
      box.append(
        el('button', {
          type: 'button', class: 'flavor', 'aria-pressed': String(on),
          onclick: () => { state.flavor = m.name; render(); },
        },
          el('span', { class: 'f-name' }, m.name),
          el('span', { class: 'f-price' }, peso(priceOf(m)))
        )
      );
    });
  }

  function renderCart() {
    const box = $('cart');
    box.replaceChildren();
    if (!state.cart.length) {
      box.append(el('p', { class: 'muted pad' }, 'Wala pang laman. Pumili ng flavor sa taas.'));
      return;
    }
    state.cart.forEach((c, i) => {
      const title = c.custom ? c.name : c.name + ' · ' + c.size + ' pcs';
      const sub = c.custom ? 'Custom item' : (c.spicy ? 'Spicy' : 'Hindi spicy');
      box.append(
        el('div', { class: 'cart-line' },
          el('div', { class: 'cart-text' },
            el('span', { class: 'cart-title' }, title),
            el('span', { class: 'cart-sub' }, sub)),
          el('span', { class: 'cart-price' }, peso(c.price)),
          el('button', {
            type: 'button', class: 'icon-btn', 'aria-label': 'Alisin ang item',
            onclick: () => { state.cart.splice(i, 1); render(); },
          }, 'Alisin')
        )
      );
    });
  }

  function render() {
    renderFlavors();
    renderCart();
    syncSeg('sizes', state.size);
    syncSeg('packs', state.pack);
    syncSeg('pays', state.pay);
    $('spicy').setAttribute('aria-checked', String(state.spicy));
    $('paid').setAttribute('aria-checked', String(state.paid));
    $('paid-text').textContent = state.paid ? 'Bayad na' : 'Hindi pa bayad';

    const cur = MENU.find((m) => m.name === state.flavor);
    const add = $('add');
    add.disabled = !cur;
    add.textContent = cur
      ? 'Idagdag · ' + cur.name + ' ' + state.size + ' pcs · ' + peso(priceOf(cur))
      : 'Idagdag';

    const total = state.cart.reduce((a, c) => a + c.price, 0);
    $('total').textContent = peso(total);
    $('summary-line').textContent =
      state.cart.length + ' item · ' + state.pay + ' · ' + (state.paid ? 'Paid' : 'Unpaid');
    $('save').disabled = state.saving || state.cart.length === 0;
  }

  bindSeg('sizes', 'size', (v) => parseInt(v, 10));
  bindSeg('packs', 'pack');
  bindSeg('pays', 'pay');

  $('spicy').addEventListener('click', () => { state.spicy = !state.spicy; render(); });
  $('paid').addEventListener('click', () => { state.paid = !state.paid; render(); });

  $('add').addEventListener('click', () => {
    const m = MENU.find((x) => x.name === state.flavor);
    if (!m) return;
    state.cart.push({ name: m.name, size: state.size, spicy: state.spicy, price: priceOf(m), custom: false });
    render();
  });

  $('c-add').addEventListener('click', () => {
    const name = $('c-name').value.trim();
    const price = parseInt($('c-price').value, 10);
    if (!name || Number.isNaN(price) || price < 0) {
      $('c-name').focus();
      return;
    }
    state.cart.push({ name, price, custom: true });
    $('c-name').value = '';
    $('c-price').value = '';
    render();
  });

  $('save').addEventListener('click', async () => {
    if (state.saving || !state.cart.length) return;
    state.saving = true;
    $('error').hidden = true;
    render();
    try {
      const res = await fetch(app.dataset.apiUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          items: state.cart,
          customer: $('who').value,
          note: $('note').value,
          pay_method: state.pay,
          paid: state.paid,
          packaging: state.pack,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Hindi na-save ang order.');
      window.location.href = app.dataset.ordersUrl + '?saved=' + data.queue_no;
    } catch (err) {
      $('error').textContent = err.message || 'Hindi na-save. Subukan ulit.';
      $('error').hidden = false;
      state.saving = false;
      render();
    }
  });

  render();
})();
