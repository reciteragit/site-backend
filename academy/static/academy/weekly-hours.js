(function () {
  function initialize(root) {
    if (root.dataset.ready) return;
    root.dataset.ready = 'true';
    const field = root.querySelector('textarea');
    const container = root.querySelector('[data-weekly-days]');
    const names = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
    let stored;
    try { stored = JSON.parse(field.value); } catch { stored = []; }
    const days = names.map((_, day) => ({ day, ranges: (Array.isArray(stored) ? stored.find(row => row.day === day)?.ranges : []) || [] }));
    function sync() { field.value = JSON.stringify(days); field.dispatchEvent(new Event('change', { bubbles: true })); }
    function element(tag, text, className) { const node = document.createElement(tag); if (text) node.textContent = text; if (className) node.className = className; return node; }
    function button(text, label, callback) { const node = element('button', text); node.type = 'button'; node.setAttribute('aria-label', label); node.addEventListener('click', callback); return node; }
    function render() {
      container.replaceChildren();
      [6,0,1,2,3,4,5].forEach(day => {
        const value = days[day];
        const card = element('div', '', 'weekly-editor-day');
        const header = element('div', '', 'weekly-editor-heading');
        header.append(element('strong', names[day]));
        const add = button('+ Add range', 'Add range for ' + names[day], () => { value.ranges.push({start:'09:00',end:'10:00'}); sync(); render(); });
        add.disabled = value.ranges.length >= 6;header.append(add);card.append(header);
        if (!value.ranges.length) card.append(element('small', 'Unavailable'));
        value.ranges.forEach((range,index) => {
          const row = element('div', '', 'weekly-editor-range');
          ['start','end'].forEach(key => {
            const label = element('label');label.append(element('span', names[day] + ' range ' + (index+1) + ' ' + key, 'weekly-editor-sr-only'));
            const input = element('input');input.type='time';input.required=true;input.value=range[key];input.addEventListener('change',()=>{range[key]=input.value;sync();});label.append(input);row.append(label);
          });
          row.append(button('×', 'Remove '+names[day]+' range '+(index+1),()=>{value.ranges.splice(index,1);sync();render();}));card.append(row);
        });
        if (value.ranges.length) card.append(button('Copy to weekdays', 'Copy '+names[day]+' hours to weekdays',()=>{for(let d=0;d<5;d++)days[d].ranges=value.ranges.map(range=>({...range}));sync();render();}));
        container.append(card);
      });
    }
    const form = root.closest('form');
    const kind = form?.querySelector('[name="kind"]');
    const duration = form?.querySelector('[name="duration_minutes"]');
    if (kind && duration) {
      const updateKind = () => { duration.readOnly = kind.value === 'trial'; if (duration.readOnly) duration.value = '15'; };
      kind.addEventListener('change', updateKind);updateKind();
    }
    sync();render();
  }
  function all() { document.querySelectorAll('[data-weekly-editor]').forEach(initialize); }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',all);else all();
})();
