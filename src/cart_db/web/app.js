'use strict';

// Find one DOM element using the selectors shared with index.html.
const $ = s => document.querySelector(s);
const types = {
  binder: '结合域 Binder',
  car: 'CAR 骨架',
  manufacturing: '制造工艺',
  abc_combination_db1: '实体组合',
  evidence: '来源证据'
};
const keys = {
  binder: 'binder_id',
  car: 'car_id',
  manufacturing: 'manufacturing_id',
  abc_combination_db1: 'combination_id',
  evidence: 'record_id'
};
const states = {
  resolved: '本次匹配完成',
  unresolved: '匹配结果待确认',
  similar: '类似工艺',
  conflict: '匹配信息冲突'
};
const labels = {
  name: '名称',
  aliases: '别名',
  scfv_sequence: 'scFv 序列',
  heavy_chain: '重链',
  light_chain: '轻链',
  linker: '连接肽',
  target_antigen: '靶抗原',
  modules: '有序组件',
  selection_steps: '细胞分选',
  activation_method: '细胞激活',
  vector_type: '基因导入方式',
  culture_system: '扩增体系',
  culture_duration: '培养周期',
  source_type: '来源类型',
  source_id: '来源编号',
  citation: '引用信息',
  applicable_scenario: '适用情境',
  contrary_evidence: '相反证据',
  t_cell_source: 'T 细胞来源',
  formulation: '制剂',
  cryopreservation_conditions: '冻存条件',
  module_type: '组件类型',
  source_molecule: '组件名称',
  sequence: '序列',
  raw: '原文记录',
  value: '数值',
  unit: '单位',
  scope: '序列范围',
  input: '输入细胞',
  output: '输出细胞',
  method: '方法',
  container: '培养容器',
  culture_mode: '培养方式',
  lower: '下限',
  upper: '上限',
  error: '误差',
  kind: '数值类型'
};
const values = {
  literature: '文献',
  patent: '专利',
  public_database: '公共数据库',
  internal_data: '内部数据',
  published: '已入库',
  pending: '待处理',
  invalid: 'QC 未通过',
  same: '身份一致',
  possible: '匹配结果待确认',
  distinct: '身份不同',
  similar: '类似工艺',
  conflict: '匹配信息冲突'
};
let metadata = {},
  tab = 'overview',
  table = 'binder',
  query = '',
  entity = '',
  page = 1,
  reviewStatus = 'unresolved',
  request = 0,
  detailRequest = 0;
// Build DOM nodes without injecting source text as HTML; callbacks become event listeners.
function node(tag, props = {}, ...children) {
  const e = document.createElement(tag);
  // Apply every property: on* binds an event, class/text use DOM properties, and other keys become attributes.
  for (const [k, v] of Object.entries(props)) {
    // Bind on* properties as event handlers, never as HTML attributes.
    if (k.startsWith('on')) e.addEventListener(k.slice(2), v);else // Set the className property for CSS classes.
      if (k === 'class') e.className = v;else // Assign textContent so scientific text is never interpreted as HTML.
        if (k === 'text') e.textContent = v;else // Other properties use ordinary DOM attributes.
          e.setAttribute(k, v);
  }
  // Flatten child lists, omit only null/undefined, and wrap non-Node values as safe text nodes.
  for (const c of children.flat()) if (c !== null && c !== undefined) e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return e;
}
// Show a request/action failure in the page-level alert banner.
function showError(e) {
  // Prefer the thrown error message; use a readable retry prompt when it is absent.
  $('#error').textContent = e.message || '加载失败，请刷新重试';
  $('#error').hidden = false;
}
// Wrap each UI action in an async handler so rejected requests reach the shared error banner.
const action = f => async () => {
  // Await synchronous or asynchronous handlers through the same error boundary.
  try {
    await f();
    // Turn a rejected action into visible feedback instead of an unhandled promise rejection.
  } catch (e) {
    showError(e);
  }
};
// Create a button whose click handler uses the shared error boundary.
const button = (text, f, cls = '') => node('button', {
  text,
  class: cls,
  onclick: action(f)
});
// Request JSON from the local read-only API, encoding parameters and bypassing browser caches.
async function api(path, params = {}) {
  const r = await fetch('/api/' + path + '?' + new URLSearchParams(params), {
    cache: 'no-store'
  });
  const d = await r.json();
  // Surface the server diagnostic on a non-success HTTP status, falling back to the status code.
  if (!r.ok) throw Error(d.error || '读取失败');
  return d;
}
// Prefer curated field labels, then a short schema description, then the original field name.
function label(k, t = table) {
  // Fall back through curated labels, schema descriptions, and the raw key in that order.
  return labels[k] || metadata[t]?.[k]?.description?.split(/[。；\n]/)[0]?.slice(0, 38) || k;
}
// Treat zero and false as reported values; only null, undefined, and empty strings are missing.
function present(v) {
  // All missing-value checks must pass so zero and false stay visible.
  return v !== null && v !== undefined && v !== '';
}
// Format nested scientific values for display without changing their stored representation.
function format(v) {
  // Show an explicit missing-value label for null/undefined.
  if (v === null || v === undefined) return '未报告';
  // Translate both boolean outcomes into readable Chinese labels.
  if (typeof v === 'boolean') return v ? '是' : '否';
  // Recursively format array items in their original order, one per line.
  if (Array.isArray(v)) return v.map(format).join('\n');
  // For objects, filter out missing members and format each remaining key/value pair recursively.
  if (typeof v === 'object') return Object.entries(v).filter(([, x]) => present(x)).map(([k, x]) => `${labels[k] || k}：${format(x)}`).join('\n');
  // Translate known enum values; retain unfamiliar values as text.
  return values[v] || String(v);
}
// Render reported fields as a definition list with schema descriptions and sequence styling.
function fields(data, t) {
  const dl = node('dl', {
    class: 'fields'
  });
  // Keep reported values and hide *_id fields because relationship links display those separately.
  const pairs = Object.entries(data || {}).filter(([k, v]) => present(v) && !k.endsWith('_id'));
  // Explain an empty field list rather than displaying a blank panel.
  if (!pairs.length) return node('p', {
    class: 'muted',
    text: '未报告其他字段。'
  });
  // Render each remaining field with its label, schema tooltip, and formatted value.
  for (const [k, v] of pairs) {
    const dt = node('dt', {
      // An undocumented field has an empty tooltip rather than invented schema help.
      title: metadata[t]?.[k]?.description || '',
      text: label(k, t)
    }, node('small', {
      text: k
    }));
    dl.append(dt, node('dd', {
      // Use monospace only for sequence fields; ordinary values keep the default text style.
      class: k.includes('sequence') ? 'seq' : '',
      text: format(v)
    }));
  }
  return dl;
}
// Show identity status with conflict/warning colors; fall back to the literal status when unknown.
function badge(status) {
  return node('span', {
    // Use red for conflict, amber for unresolved, and the default badge style otherwise.
    class: 'tag ' + (status === 'conflict' ? 'conflict' : status === 'unresolved' ? 'warning' : ''),
    // Translate known statuses and display unknown ones literally.
    text: states[status] || status
  });
}
// Wrap a heading, optional subtitle, and content in the common panel layout.
function panel(title, body, sub = '') {
  return node('section', {
    class: 'panel'
  }, node('div', {
    class: 'panel-head'
  }, node('h2', {
    text: title
  }), node('span', {
    class: 'muted',
    text: sub
  })), body);
}
// Build a table from column labels and pre-rendered body rows.
function grid(headers, rs) {
  // An empty result gets one full-width placeholder row so the table remains understandable.
  if (!rs.length) rs = [node('tr', {}, node('td', {
    colspan: headers.length,
    class: 'empty',
    text: '暂无记录'
  }))];
  return node('div', {
    class: 'table-wrap'
    // Map each column label to its own header cell, keeping the caller-provided column order.
  }, node('table', {}, node('thead', {}, node('tr', {}, headers.map(h => node('th', {
    text: h
  })))), node('tbody', {}, rs)));
}
// Render 20-row pagination; previous/next callbacks request adjacent pages and disable at boundaries.
function pager(total, current, onPage) {
  const last = Math.max(1, Math.ceil(total / 20));
  // The previous-page callback requests one page before the current page.
  const prev = button('上一页', () => onPage(current - 1)),
    // The next-page callback requests one page after the current page.
    next = button('下一页', () => onPage(current + 1));
  prev.disabled = current <= 1;
  next.disabled = current >= last;
  return node('div', {
    class: 'pager'
  }, node('span', {
    text: `共 ${total} 条 · ${current} / ${last} 页`
  }), prev, next);
}
// Switch tabs and reset pagination/entity filtering so state from the prior view does not leak.
function go(next) {
  tab = next;
  page = 1;
  entity = '';
  load();
}
// Load the active page and use a request ticket to prevent stale responses replacing newer views.
async function load() {
  const ticket = ++request;
  $('#error').hidden = true;
  $('#content').replaceChildren(node('div', {
    class: 'loading',
    text: '正在读取数据库…'
  }));
  $('#title').textContent = {
    overview: '数据总览',
    browse: '实体与证据',
    reviews: '匹配检查'
  }[tab];
  // Mark only the button matching the active tab as selected.
  document.querySelectorAll('[data-tab]').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  // Resolve the selected view inside one page-level error boundary.
  try {
    // Dispatch to overview, entity browsing, or review listing according to the current tab.
    const body = tab === 'overview' ? await overview() : tab === 'browse' ? await browse() : await reviewList();
    // Discard a response if another navigation started while this request was in flight.
    if (ticket !== request) return;
    $('#content').replaceChildren(body);
    $('#updated').textContent = '更新于 ' + new Date().toLocaleTimeString('zh-CN', {
      hour12: false
    });
    // Handle request/render failures without allowing an older failed request to replace a newer page.
  } catch (e) {
    // Only the newest request may display its error state.
    if (ticket === request) {
      $('#content').replaceChildren(node('div', {
        class: 'empty',
        text: '暂时无法读取数据，请检查数据库连接后刷新。'
      }));
      showError(e);
    }
  }
}
// Build the overview from database totals, identity-review counts, and recent import batches.
async function overview() {
  const d = await api('summary');
  const root = node('div');
  root.append(node('section', {
    class: 'hero'
  }, node('div', {}, node('h2', {
    text: '从实体到证据，让数据可查可溯'
  }), node('p', {
    text: '浏览结合域、CAR 骨架和制造工艺，查看独立来源证据，核查匹配结果。所有内容直接读取当前数据库。'
  })), node('div', {
    class: 'hero-mark',
    text: 'A · B · C'
  })));
  const cards = node('div', {
    class: 'cards'
  });
  // Create one navigation card per source/entity/evidence total.
  for (const [key, title] of [['sources', '文献及其他来源'], ['binder', '结合域'], ['car', 'CAR 骨架'], ['manufacturing', '制造工艺'], ['evidence', '来源证据']]) {
    // A card click selects its table (sources use evidence), clears search, and opens browsing.
    const c = button('', () => {
      // The sources card opens evidence, where source IDs are stored; other cards open their own table.
      table = key === 'sources' ? 'evidence' : key;
      query = '';
      go('browse');
    }, 'card');
    c.append(node('span', {
      class: 'muted',
      text: title
    }), node('strong', {
      class: 'number',
      // Read top-level totals when available, then per-table counts, with zero as the empty default.
      text: d[key] ?? d.counts[key] ?? 0
    }), node('span', {
      class: 'muted',
      // Distinguish the source-card caption from scientific record counts.
      text: key === 'sources' ? '按来源类型与编号去重' : '查看记录 →'
    }));
    cards.append(c);
  }
  root.append(cards);
  const checks = node('div', {
    class: 'review-counts'
  });
  // Create a shortcut for each review status that needs attention.
  for (const s of ['unresolved', 'similar', 'conflict']) {
    // A review shortcut selects that status and opens the review tab from its first page.
    const b = button('', () => {
      reviewStatus = s;
      go('reviews');
    });
    b.append(badge(s), node('strong', {
      // An absent review-status count displays as zero.
      text: d.states[s] || 0
    }));
    checks.append(b);
  }
  root.append(panel('匹配检查', node('div', {
    class: 'panel-body'
  }, checks, node('p', {
    class: 'muted',
    text: '按入库来源记录计数，同一实体可能对应多条记录。待确认与冲突不阻塞来源证据保存。'
  }))));
  // Map recent batches to rows showing their provenance and publication counts.
  const rs = d.batches.map(b => node('tr', {}, node('td', {}, node('strong', {
    text: b.input_name.split(/[\\/]/).slice(-2).join('/')
  })), node('td', {
    text: new Date(b.created_at).toLocaleString('zh-CN', {
      hour12: false
    })
  }), node('td', {
    text: b.published
  }), node('td', {
    text: b.pending
  }), node('td', {
    text: b.invalid
  })));
  root.append(panel('最近入库批次', grid(['来源文件', '入库时间', '已入库', '待处理', 'QC 未通过'], rs), '最近 8 批'));
  return root;
}
// Load one table using the current search, page, and optional evidence-owner filter.
async function browse() {
  const d = await api('list', {
    table,
    q: query,
    page,
    // Send an entity filter only when navigating from a specific record.
    ...(entity ? {
      entity
    } : {})
  });
  const root = node('div'),
    select = node('select', {
      'aria-label': '数据类型'
    });
  // Add all supported scientific tables to the selector and select the active table.
  for (const [k, v] of Object.entries(types)) {
    const o = node('option', {
      value: k,
      text: v
    });
    o.selected = k === table;
    select.append(o);
  }
  // Changing tables clears the prior entity filter and starts again at page one.
  select.addEventListener('change', () => {
    table = select.value;
    entity = '';
    page = 1;
    load();
  });
  const input = node('input', {
    placeholder: '搜索名称、别名、来源编号或记录内容',
    'aria-label': '搜索记录',
    value: query
  });
  const form = node('form', {
    class: 'toolbar'
  }, select, input, node('button', {
    type: 'submit',
    text: '搜索'
  }));
  // Handle search locally: prevent form navigation, store the query, and reload from page one.
  form.addEventListener('submit', e => {
    e.preventDefault();
    query = input.value;
    page = 1;
    load();
  });
  root.append(form);
  // Explain an active entity filter and offer a callback that clears it before reloading.
  if (entity) root.append(node('div', {
    class: 'notice'
  }, '正在查看所选实体或组合关联的证据。 ', button('清除筛选', () => {
    entity = '';
    page = 1;
    load();
  })));
  // Map each result to a display row with record-opening callbacks and a table-specific summary.
  const rs = d.items.map(r => {
    const id = r[keys[table]],
      // Prefer a reported name/source ID; use a combination label or shortened UUID when neither exists.
      name = r.name || r.source_id || (table === 'abc_combination_db1' ? '实体组合' : '未命名记录');
    // Choose target, ordered module names, vector type, evidence citation/scenario, or combination summary by table.
    const brief = table === 'binder' ? r.target_antigen || '靶抗原未报告' : table === 'car' ? (r.modules || []).map(m => m.source_molecule || m.module_type).join(' → ') : table === 'manufacturing' ? r.vector_type || '导入方式未报告' : table === 'evidence' ? r.citation || r.applicable_scenario || '查看来源与观测字段' : '结合域 + CAR 骨架 + 制造工艺';
    // Open the selected record when its name is clicked.
    return node('tr', {}, node('td', {}, button(name, () => openRecord(table, id), 'link'), node('div', {
      class: 'muted',
      text: id.slice(0, 8)
    })), node('td', {
      // Truncate only the displayed summary after 150 characters; detail data stays intact.
      text: brief.length > 150 ? brief.slice(0, 150) + '…' : brief
      // The detail button opens the same record as the name link.
    }), node('td', {}, button('查看详情 →', () => openRecord(table, id), 'link')));
  });
  // A page selection updates shared pagination and reloads the current table/search.
  root.append(panel(types[table], node('div', {}, grid(['名称 / 来源', '主要信息', '操作'], rs), pager(d.total, d.page, p => {
    page = p;
    load();
  })), `${d.total} 条记录`));
  return root;
}
// Fetch and render staged identity decisions filtered by review status.
async function reviewList() {
  const d = await api('reviews', {
    status: reviewStatus,
    page
  });
  const root = node('div'),
    tools = node('div', {
      class: 'toolbar'
    });
  // Render the supported status filters without changing server-side review decisions.
  for (const s of ['unresolved', 'similar', 'conflict']) {
    // Selecting a status resets pagination and reloads its review list.
    const b = button(states[s], () => {
      reviewStatus = s;
      page = 1;
      load();
    });
    // Highlight only the currently selected review filter.
    if (s === reviewStatus) b.classList.add('tag');
    tools.append(b);
  }
  root.append(tools, node('p', {
    class: 'muted',
    text: '查看入库时保存的匹配判断。这里仅供核查，不会自动合并或修改数据。'
  }));
  // Map review rows to source descriptions, identity states, and comparison-opening callbacks.
  const rs = d.items.map(r => node('tr', {}, node('td', {}, node('strong', {
    text: r.name || '未命名记录'
  }), node('div', {
    class: 'muted',
    text: types[r.table_name]
  })), node('td', {
    text: r.input_name.split(/[\\/]/).slice(-2).join('/') + ' · 第 ' + r.line_number + ' 行'
    // Open the identity comparison for the selected staging record.
  }), node('td', {}, badge(r.identity_status)), node('td', {}, button('对比与理由 →', () => openReview(r.stage_id), 'link'))));
  // Review pagination updates the current page and reloads the list.
  root.append(panel('需要核查的来源记录', node('div', {}, grid(['记录', '来源', '状态', '操作'], rs), pager(d.total, d.page, p => {
    page = p;
    load();
  }))));
  return root;
}
// Prepare the shared detail dialog and issue a ticket for its newest content request.
function startDialog(title) {
  $('#detail-title').textContent = title;
  $('#detail-body').replaceChildren(node('div', {
    class: 'loading',
    text: '正在读取详情…'
  }));
  // Open the modal only when closed; refreshing an open modal must not call showModal again.
  if (!$('#detail').open) $('#detail').showModal();
  return ++detailRequest;
}
// Load an accepted record, its linked entities, and paged source assertions into the dialog.
async function openRecord(t, id, sourcePage = 1) {
  const ticket = startDialog('记录详情');
  // Keep detail loading/rendering errors within the dialog rather than replacing the main page.
  try {
    const d = await api('detail', {
      table: t,
      id,
      page: sourcePage
    });
    // Discard detail content if the user closed the dialog or opened another detail request.
    if (ticket !== detailRequest) return;
    // Use a reported name, then source ID, then the table label for the detail heading.
    $('#detail-title').textContent = d.data.name || d.data.source_id || types[t];
    const body = node('div', {}, node('p', {
      class: 'muted',
      text: types[t] + ' · ' + id
    }));
    // Show known source names only when the server supplied any.
    if (d.names.length) body.append(node('p', {
      text: '来源名称：' + d.names.join(' / ')
    }));
    const links = node('div', {
      class: 'record-links'
    });
    // For an entity, the evidence-link callback closes details and opens evidence filtered to that entity.
    if (t !== 'evidence') links.append(button('查看关联证据 →', () => {
      $('#detail').close();
      table = 'evidence';
      entity = id;
      query = '';
      page = 1;
      tab = 'browse';
      load();
    }));
    // Inspect each possible entity owner to expose explicit foreign-key navigation.
    for (const other of ['binder', 'car', 'manufacturing', 'abc_combination_db1']) {
      const fk = keys[other];
      // Link only to a different table with a reported foreign key; each callback opens that owner.
      if (other !== t && d.data[fk]) links.append(button(types[other] + ' →', () => openRecord(other, d.data[fk])));
    }
    body.append(links, fields(d.data, t), node('h3', {
      text: '来源记录与抽取依据'
    }), node('p', {
      class: 'muted',
      text: '下方保留每次导入的原始记录。抽取依据可能包含整篇文章的说明，不等同于每个字段都已人工核实。'
    }));
    // Keep every source assertion in its own expandable section with original and normalized fields.
    for (const s of d.sources) {
      const box = node('details', {}, node('summary', {
        text: s.input_name.split(/[\\/]/).slice(-2).join('/') + ' · 第 ' + s.line_number + ' 行'
      }));
      const tools = node('div', {
        class: 'source-tools'
      });
      // Show identity audit information only when the assertion includes an identity status.
      if (s.identity_status) {
        tools.append(badge(s.identity_status));
        // Unresolved/non-resolved identity states offer a callback to inspect their candidate comparison.
        if (s.identity_status !== 'resolved') tools.append(button('查看匹配依据', () => openReview(s.stage_id)));
      }
      // Add a lazy-loading callback for each available context attachment; absent context lists are empty.
      for (const c of s.contexts || []) tools.append(button(c.name.split(/[\\/]/).pop(), async () => {
        const data = await api('context', {
          batch: s.batch_id,
          name: c.name,
          checksum: c.checksum
        });
        let pre = box.querySelector('.text-block');
        // Create the context text area on first load, then reuse it for later clicks.
        if (!pre) {
          pre = node('div', {
            class: 'text-block'
          });
          box.append(pre);
        }
        pre.textContent = data.content;
      }));
      box.append(tools, node('pre', {
        text: JSON.stringify(s.original, null, 2)
      }));
      body.append(box);
    }
    // Explain when this record has no source assertions to display.
    if (!d.total) body.append(node('p', {
      class: 'muted',
      text: '没有保存的导入来源记录。'
    }));
    // More than 20 assertions need pagination; the callback reloads this record at the selected source page.
    if (d.total > 20) body.append(pager(d.total, d.page, p => openRecord(t, id, p)));
    $('#detail-body').replaceChildren(body);
    // Display record-loading failures inside the detail dialog.
  } catch (e) {
    $('#detail-body').replaceChildren(node('p', {
      text: e.message
    }));
  }
}
// Compare one staged source assertion with its identity candidates using the saved audit details.
async function openReview(id) {
  const ticket = startDialog('匹配依据与记录对比');
  // Keep candidate loading and comparison rendering under the dialog error boundary.
  try {
    const d = await api('review', {
      id
    });
    // Ignore candidate results for a dialog that was closed or superseded.
    if (ticket !== detailRequest) return;
    const r = d.record,
      t = r.table_name,
      body = node('div', {}, badge(r.identity_status), node('p', {
        class: 'notice',
        text: '以下为入库时记录的匹配理由；右侧实体字段读取自当前数据库。缺失字段以“未报告”显示，不表示一致。'
      }), node('p', {
        // Show the saved identity reason, or state explicitly that no reason was saved.
        text: r.identity_details?.reason || '未保存判断理由。'
        // Open the source assertion record from its table and primary-key value.
      }), button('查看本条记录及来源 →', () => openRecord(t, r.target_id)));
    // No saved normalization flags means an empty warning list.
    const flags = r.identity_details?.normalization_flags || [];
    // Show normalization warnings only when flags were recorded.
    if (flags.length) body.append(node('details', {}, node('summary', {
      text: '规范化检查疑点'
    }), node('pre', {
      text: JSON.stringify(flags, null, 2)
    })));
    // Render each candidate independently so alternatives and conflicts remain visible.
    for (const c of d.candidates) {
      const cp = c.comparison;
      const box = node('section', {
        class: 'panel'
      }, node('div', {
        class: 'panel-head'
      }, node('h3', {
        // Prefer the candidate name; otherwise identify it by the available accepted/staged key.
        text: '候选：' + (c.data?.name || c.id)
        // Map same/possible verdicts to the corresponding display badge and retain other verdict labels.
      }), badge(cp.verdict === 'same' ? 'resolved' : cp.verdict === 'possible' ? 'unresolved' : cp.verdict)));
      const inner = node('div', {
        class: 'panel-body'
      }, node('p', {
        // Use the saved candidate reason when available, otherwise describe the comparison basis generally.
        text: cp.reason || '依据字段比较结果判断。'
      }));
      // Use an accepted candidate primary key when available; otherwise use its saved target ID.
      const target = c.location === 'accepted' ? c.id : c.target_id;
      // Offer a record-opening callback only when a target identifier exists.
      if (target) inner.append(button('查看候选来源 →', () => openRecord(t, target)));
      inner.append(node('div', {
        class: 'legend'
      }, node('span', {}, node('i', {
        class: 'dot agree'
      }), '一致'), node('span', {}, node('i', {
        class: 'dot differ'
      }), '不同或冲突'), node('span', {}, node('i', {
        class: 'dot unknown'
      }), '未报告')));
      // For each comparison category, show a section only when saved details exist; map field names to labels.
      for (const [key, title] of [['agreements', '一致依据'], ['differences', '差异字段'], ['conflicts', '冲突字段'], ['unknown', '缺失维度']]) if (cp[key]?.length) inner.append(node('p', {
        class: 'muted',
        text: title + '：' + cp[key].map(k => label(k, t)).join('、')
      }));
      // An absent source assertion becomes an empty side of the field comparison.
      const a = r.normalized || {},
        // An absent candidate becomes an empty comparison side; missing values are marked unknown.
        b = c.data || {},
        // Compare the union of keys, excluding IDs and fields missing on both sides.
        ks = [...new Set([...Object.keys(a), ...Object.keys(b)])].filter(k => !k.endsWith('_id') && (present(a[k]) || present(b[k])));
      // Build a side-by-side row per visible field with a display-only equality indicator.
      const rs = ks.map(k => {
        const av = a[k],
          bv = b[k];
        // Missing on either side means unknown; otherwise compare serialized values for agree/differ coloring, not identity proof.
        const cls = !present(av) || !present(bv) ? 'unknown' : JSON.stringify(av) === JSON.stringify(bv) ? 'agree' : 'differ';
        return node('tr', {
          class: cls
        }, node('td', {
          text: label(k, t)
        }), node('td', {
          text: format(av)
        }), node('td', {
          text: format(bv)
        }));
      });
      const g = grid(['字段', '当前来源记录', '候选记录'], rs);
      g.querySelector('table').classList.add('comparison');
      inner.append(g);
      box.append(inner);
      body.append(box);
    }
    // Explain when retrieval found no identity candidates.
    if (!d.total) body.append(node('p', {
      class: 'muted',
      text: '没有保存疑似重复候选，请查看上方规范化检查疑点。'
    }));
    // Warn when only the first 50 candidates are shown; the total remains visible.
    if (d.total > 50) body.append(node('p', {
      class: 'notice',
      text: `共 ${d.total} 个候选，本页展示前 50 个。完整候选保留在数据库审计记录。`
    }));
    $('#detail-body').replaceChildren(body);
    // Display candidate-loading failures inside the dialog.
  } catch (e) {
    $('#detail-body').replaceChildren(node('p', {
      text: e.message
    }));
  }
}
// Bind each navigation button to its own tab through the shared action error handler.
document.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click', () => go(b.dataset.tab)));
// Refresh closes any open details and reloads the active page.
$('#refresh').addEventListener('click', () => {
  // Close the modal only if it is currently open.
  if ($('#detail').open) $('#detail').close();
  load();
});
// The close button dismisses the detail modal.
$('#close').addEventListener('click', () => $('#detail').close());
// Invalidate outstanding detail tickets when the dialog closes, including Escape-key dismissal.
$('#detail').addEventListener('close', () => {
  detailRequest++;
});
// Poll demo lifecycle state so reset/recreated demo databases refresh the UI automatically.
async function watchDemo(previous) {
  // Treat polling as background work; normal data requests are responsible for visible connection errors.
  try {
    const {
      state
    } = await api('state');
    // Reload only when the demo changes into an empty or ready state.
    if (state !== previous && (state === 'empty' || state === 'ready')) {
      // Close stale details before resetting pagination and reloading after a demo transition.
      if ($('#detail').open) $('#detail').close();
      page = 1;
      await load();
    }
    previous = state;
  } catch (e) {/* Normal data requests report connection errors. */}
  // Schedule the next poll after this attempt finishes, carrying forward the last observed state.
  setTimeout(() => watchDemo(previous), 3000);
}
// Bootstrap field metadata and mode once, then load the initial page and optional demo polling.
(async () => {
  // Report startup failures through the same visible error banner as other page requests.
  try {
    const d = await api('meta');
    metadata = d.fields;
    $('#mode').textContent = d.mode;
    // Query demo state only in demo mode; normal databases do not use the demo lifecycle endpoint.
    const initial = d.demo ? (await api('state')).state : null;
    await load();
    // Start the recurring polling callback only when the server identifies itself as a demo.
    if (d.demo) setTimeout(() => watchDemo(initial), 3000);
    // Show metadata/mode startup failures so an unusable page does not remain silently empty.
  } catch (e) {
    showError(e);
  }
})();
