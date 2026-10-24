let currentAssetKind=null,currentAssetTarget=null,currentAssetPreview=null,currentAssetName=null,currentAssetItems=[];
function openAssetPicker(kind,targetId=null,previewId=null,nameId=null){
  currentAssetKind=kind;currentAssetTarget=targetId;currentAssetPreview=previewId;currentAssetName=nameId;
  const modal=document.getElementById('assetModal'); if(!modal)return;
  const title=modal.querySelector('#assetModalTitle');
  const tabs=modal.querySelector('#assetPickerTabs');
  const grid=modal.querySelector('#assetGrid'); if(!grid)return;
  if(title)title.textContent=kind==='image'?'انتخاب تصویر':kind==='icon'?'انتخاب آیکون':'انتخاب رسانه';
  if(tabs)tabs.innerHTML='';
  grid.innerHTML='<p>در حال بارگذاری...</p>'; modal.classList.add('open');
  const endpoint=kind==='page-media'?'page-media':kind;
  fetch('/admin/api/assets/'+endpoint).then(r=>r.json()).then(items=>{
    currentAssetItems=Array.isArray(items)?items:[];
    if(kind==='page-media'){
      if(tabs){
        tabs.innerHTML='<button type="button" class="asset-tab active" data-tab="image">تصاویر</button><button type="button" class="asset-tab" data-tab="model">مدل‌های سه‌بعدی</button>';
        tabs.querySelectorAll('.asset-tab').forEach(b=>b.onclick=()=>{
          tabs.querySelectorAll('.asset-tab').forEach(x=>x.classList.toggle('active',x===b));
          renderAssetPickerItems(b.dataset.tab);
        });
      }
      renderAssetPickerItems('image');
    }else{
      renderAssetPickerItems(kind);
    }
  }).catch(()=>grid.innerHTML='<p>خطا در دریافت فایل‌ها.</p>')
}
function renderAssetPickerItems(tab){
  const grid=document.getElementById('assetGrid');if(!grid)return;
  const items=currentAssetKind==='page-media'?currentAssetItems.filter(a=>a.kind===tab):currentAssetItems;
  if(!items.length){grid.innerHTML='<p class="asset-empty">فایلی در این بخش وجود ندارد.</p>';return;}
  grid.innerHTML='';
  items.forEach(a=>{
    const el=document.createElement('div');
    el.className='picker-item '+(a.kind==='icon'?'icon ':'')+(a.kind==='model'?'model-picker-item':'');
    el.innerHTML=a.kind==='model'?`<div class="model-picker-preview" style="${a.background_url?`background-image:url('${a.background_url}')`:''}"><b>3D</b></div><span>${a.filename}</span>`:`<img class="${a.kind==='icon'?'icon-clean':''}" src="${a.url}" alt=""><span>${a.filename}</span>`;
    el.onclick=()=>selectAsset(a);grid.appendChild(el)
  })
}
function selectAsset(a){
  const stored=a.kind==='model'?'model:'+a.filename:a.filename;
  if(currentAssetTarget){const t=document.getElementById(currentAssetTarget);if(t)t.value=stored}
  if(currentAssetPreview){const p=document.getElementById(currentAssetPreview);if(p)p.src=a.kind==='model'?'/images/placeholder-modeling.png':a.url}
  if(currentAssetName){const n=document.getElementById(currentAssetName);if(n)n.textContent=a.filename}
  closeAssetPicker(); if(window.InlineAdmin?.assetSelected)window.InlineAdmin.assetSelected(a);
}
function closeAssetPicker(){document.getElementById('assetModal')?.classList.remove('open')}
function closeEditor(){document.getElementById('editorModal')?.classList.remove('open')}
let savedSelection=null,activeRichEditor=null;
function rememberEditorSelection(editor){if(editor)activeRichEditor=editor;const sel=window.getSelection();if(sel&&sel.rangeCount){const r=sel.getRangeAt(0);if(activeRichEditor && activeRichEditor.contains(r.commonAncestorContainer))savedSelection=r.cloneRange();}}
function saveSelection(){rememberEditorSelection(activeRichEditor||document.activeElement)}
function restoreSelection(){if(!savedSelection)return;const sel=window.getSelection();sel.removeAllRanges();sel.addRange(savedSelection)}

// The editor stores the three rich options as literal marker characters only.
// No <a>, <span> or <button> is inserted into the saved value.
function setRichEditorContent(editor,html){if(!editor)return;editor.innerHTML=String(html||'');}
function serializeRichEditor(editor){return editor?editor.innerHTML:'';}

// Client-side preview helper for unsaved inline editing only. It uses exactly
// the same marker syntax as the server compiler; the stored value remains text.
function compileRichSyntax(html){
  const box=document.createElement('div');box.innerHTML=String(html||'');
  const safeUrl=u=>/^(https?:\/\/|\/|#|mailto:|tel:)/i.test(String(u||'').trim())?String(u).trim():'#';
  const esc=t=>String(t||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  const walker=document.createTreeWalker(box,NodeFilter.SHOW_TEXT),nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
  nodes.forEach(node=>{const parent=node.parentElement;if(!parent||/^(SCRIPT|STYLE|TEXTAREA)$/i.test(parent.tagName))return;const text=node.nodeValue||'';const re=(/\[[^\[\]\n]+\]|\{[^{}\n|]+\|\|[^{}\n|]+\}|\{[^{}\n|]+\|[^{}\n|]+\}/g);let last=0,m,frag=document.createDocumentFragment(),changed=false;while((m=re.exec(text))){changed=true;if(m.index>last)frag.appendChild(document.createTextNode(text.slice(last,m.index)));const token=m[0];if(token[0]==='['){const el=document.createElement('span');el.className='rich-box';el.textContent=token.slice(1,-1);frag.appendChild(el);}else{const body=token.slice(1,-1),isButton=body.includes('||'),sep=isButton?'||':'|',cut=body.indexOf(sep),el=document.createElement('a');el.className=isButton?'rich-button':'rich-link';el.href=safeUrl(body.slice(cut+sep.length));el.textContent=body.slice(0,cut);frag.appendChild(el);}last=m.index+token.length;}if(changed){if(last<text.length)frag.appendChild(document.createTextNode(text.slice(last)));node.parentNode.replaceChild(frag,node);}});return box.innerHTML;
}
function richPreviewHtml(html){return compileRichSyntax(html);}
function formatText(cmd,value=null){restoreSelection();document.execCommand(cmd,false,value);saveSelection();notifyRichEditorChange()}
function openTextTools(){rememberEditorSelection(document.activeElement);document.getElementById('textToolsModal')?.classList.add('open')}
function closeTextTools(){document.getElementById('textToolsModal')?.classList.remove('open')}
function applyTextTools(){restoreSelection();const font=document.getElementById('fontName')?.value;const size=document.getElementById('fontSize')?.value;const color=document.getElementById('fontColor')?.value;if(font)document.execCommand('fontName',false,font);if(size)document.execCommand('fontSize',false,size);if(color)document.execCommand('foreColor',false,color);saveSelection();notifyRichEditorChange();closeTextTools()}
function resetSelectedTextFormat(){restoreSelection();document.execCommand('removeFormat',false,null);saveSelection();notifyRichEditorChange();}

// Changes only the font size of the selected text; all other formatting is preserved.
function applySelectedFontSizeOnly(){const ed=document.getElementById('inlineTextEditor');if(!ed)return;rememberEditorSelection(ed);restoreSelection();const size=document.getElementById('inlineSize')?.value;if(size)document.execCommand('fontSize',false,size);saveSelection();InlineAdmin.liveModalPreview();ed.focus();}

function ensureRichUrlModal(){
  let m=document.getElementById('richUrlModal');if(m)return m;
  m=document.createElement('div');m.id='richUrlModal';m.className='modal';
  m.innerHTML='<div class="modal-card rich-url-modal"><button class="modal-close" type="button" id="richUrlClose">×</button><h2 id="richUrlTitle">افزودن لینک</h2><p class="muted" id="richUrlHelp">لینک موردنظر را وارد کنید.</p><label class="rich-url-field">لینک<input id="richUrlInput" type="url" dir="ltr" placeholder="https://example.com" autocomplete="off"></label><div class="modal-actions"><button class="btn primary" type="button" id="richUrlOk">افزودن</button><button class="btn ghost" type="button" id="richUrlCancel">انصراف</button></div></div>';
  document.body.appendChild(m);
  return m;
}
function openRichUrlDialog(type,selected,range){
  const m=ensureRichUrlModal(),input=m.querySelector('#richUrlInput');
  m.querySelector('#richUrlTitle').textContent=type==='button'?'افزودن دکمه':'افزودن هایپرلینک';
  m.querySelector('#richUrlHelp').textContent=type==='button'?'لینک دکمه را وارد کنید؛ فرمت آن به‌صورت خودکار ساخته می‌شود.':'لینک هایپرلینک را وارد کنید؛ فرمت آن به‌صورت خودکار ساخته می‌شود.';
  input.value='';m.classList.add('open');setTimeout(()=>input.focus(),0);
  const close=()=>m.classList.remove('open');
  m.querySelector('#richUrlClose').onclick=close;m.querySelector('#richUrlCancel').onclick=close;
  m.querySelector('#richUrlOk').onclick=()=>{const url=input.value.trim();if(!/^(https?:\/\/|\/|#|mailto:|tel:)/i.test(url)){alert('لطفاً یک لینک معتبر وارد کنید.');input.focus();return;}restoreSelection();const sel=window.getSelection();if(!sel||!sel.rangeCount){close();return;}const r=range||sel.getRangeAt(0);r.deleteContents();r.insertNode(document.createTextNode(type==='button'?'{'+selected+'||'+url+'}':'{'+selected+'|'+url+'}'));r.collapse(false);saveSelection();notifyRichEditorChange();close();activeRichEditor?.focus();};
  input.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();m.querySelector('#richUrlOk').click()}if(e.key==='Escape')close()};
}
function insertRichSyntax(type){
  restoreSelection();const sel=window.getSelection();
  if(!sel||!sel.rangeCount||sel.isCollapsed){alert('ابتدا متن موردنظر را انتخاب کنید.');return;}
  const selected=sel.toString();if(!selected){alert('ابتدا متن موردنظر را انتخاب کنید.');return;}
  const range=sel.getRangeAt(0).cloneRange();
  if(type==='box'){range.deleteContents();range.insertNode(document.createTextNode('['+selected+']'));range.collapse(false);saveSelection();notifyRichEditorChange();activeRichEditor?.focus();return;}
  if(type==='link'||type==='button'){openRichUrlDialog(type,selected,range);}
}
function setActiveInlineAndInsert(type){const ed=document.getElementById('inlineTextEditor');if(ed){activeRichEditor=ed;restoreSelection();}insertRichSyntax(type);ed?.focus()}

function notifyRichEditorChange(){
  if(window.InlineAdmin?.active?.modalState) window.InlineAdmin.liveModalPreview();
  const ed=activeRichEditor||document.activeElement;
  if(ed?.id==='bodyEditor'){const x=document.getElementById('bodyValue');if(x)x.value=serializeRichEditor(ed);}
  if(ed?.id==='titleEditor'){const x=document.getElementById('titleValue');if(x)x.value=serializeRichEditor(ed);}
}
function bindRichEditor(editor){if(!editor||editor.dataset.richBound)return;editor.dataset.richBound='1';editor.addEventListener('focus',()=>{activeRichEditor=editor;saveSelection()});editor.addEventListener('mouseup',()=>saveSelection());editor.addEventListener('keyup',()=>saveSelection());editor.addEventListener('input',()=>{activeRichEditor=editor;saveSelection();notifyRichEditorChange()});editor.addEventListener('touchend',()=>saveSelection())}
document.addEventListener('selectionchange',()=>{const a=document.activeElement;if(a?.isContentEditable)rememberEditorSelection(a)});

function applyInlineTextTools(){const ed=document.getElementById('inlineTextEditor');if(!ed)return;rememberEditorSelection(ed);restoreSelection();const font=document.getElementById('inlineFont')?.value;const size=document.getElementById('inlineSize')?.value;const color=document.getElementById('inlineColor')?.value;if(font)document.execCommand('fontName',false,font);if(size)document.execCommand('fontSize',false,size);if(color)document.execCommand('foreColor',false,color);saveSelection();InlineAdmin.liveModalPreview();ed.focus()}

function setActiveInlineAndInsert(type){const ed=document.getElementById('inlineTextEditor');if(ed){activeRichEditor=ed;restoreSelection();}insertRichSyntax(type);if(window.InlineAdmin?.liveModalPreview)window.InlineAdmin.liveModalPreview();ed?.focus()}

const InlineAdmin={
  active:null, modal:null, modalState:null,
  ensureModal(){
    if(this.modal)return this.modal;
    const m=document.createElement('div');m.id='inlineFieldModal';m.className='modal';
    m.innerHTML=`<div class="modal-card inline-field-modal"><button class="modal-close" type="button" id="inlineFieldClose">×</button><h2 id="inlineFieldTitle">ویرایش متن</h2><div id="inlineTextEditor" class="rich-editor" contenteditable="true" dir="rtl"></div><div class="rich-editor-bar inline-toolbar"><button type="button" onclick="setActiveInlineAndInsert('box')">▣ کادر</button><button type="button" onclick="setActiveInlineAndInsert('link')">🔗 هایپرلینک</button><button type="button" onclick="setActiveInlineAndInsert('button')">▣ دکمه</button><button type="button" data-cmd="justifyRight">راست</button><button type="button" data-cmd="justifyCenter">وسط</button><button type="button" data-cmd="justifyLeft">چپ</button><button type="button" data-cmd="bold"><b>B</b></button><button type="button" data-cmd="italic"><i>I</i></button><button type="button" data-cmd="underline"><u>U</u></button><select id="inlineFont"><option value="Tahoma">Tahoma</option><option value="Arial">Arial</option><option value="Georgia">Georgia</option><option value="Verdana">Verdana</option><option value="Times New Roman">Times New Roman</option></select><select id="inlineSize"><option value="1">خیلی کوچک</option><option value="2">کوچک</option><option value="3" selected>متوسط</option><option value="4">بزرگ</option><option value="5">خیلی بزرگ</option><option value="6">بسیار بزرگ</option></select><input id="inlineColor" type="color" value="#ffffff"><button type="button" onclick="applySelectedFontSizeOnly()">اعمال فقط اندازه فونت</button><button type="button" onclick="applyInlineTextTools()">اعمال قالب</button><button type="button" onclick="resetSelectedTextFormat()">بازگردانی فرمت پیش‌فرض</button></div><div class="inline-syntax-guide"><div><b>کادر:</b> <code>[متن]</code> — فقط متن این فرمت ذخیره می‌شود و هنگام نمایش به کادر تبدیل می‌شود.</div><div><b>هایپرلینک:</b> <code>{متن|link}</code> — با دکمه بالا لینک در پنجره جداگانه وارد می‌شود.</div><div><b>دکمه:</b> <code>{متن||link}</code> — با دکمه بالا لینک در پنجره جداگانه وارد می‌شود.</div></div><div class="modal-actions"><button class="btn primary" type="button" id="inlineFieldOk">تأیید</button><button class="btn ghost" type="button" id="inlineFieldCancel">انصراف</button></div></div>`;
    document.body.appendChild(m);this.modal=m;
    const inlineEditor=m.querySelector('#inlineTextEditor');bindRichEditor(inlineEditor);inlineEditor.addEventListener('input',()=>this.liveModalPreview());
    m.querySelector('#inlineFieldClose').onclick=()=>this.closeFieldModal();m.querySelector('#inlineFieldCancel').onclick=()=>this.closeFieldModal();m.querySelector('#inlineFieldOk').onclick=()=>this.saveFieldModal();
    m.querySelectorAll('[data-cmd]').forEach(b=>b.onclick=()=>{rememberEditorSelection(m.querySelector('#inlineTextEditor'));document.execCommand(b.dataset.cmd,false,null);saveSelection();this.liveModalPreview();m.querySelector('#inlineTextEditor').focus()});
    return m;
  },
  showLocalActions(root,mode){
    root.querySelectorAll(':scope > .inline-local-actions').forEach(x=>x.remove());
    const bar=document.createElement('div');
    bar.className='inline-local-actions';
    const isSolutionCard=mode==='entity' && this.active?.type==='card' && root.closest('[data-card-collection]')?.dataset.cardCollection==='solution';
    const videoForm=isSolutionCard?`<form class="inline-video-upload" method="post" enctype="multipart/form-data" action="/admin/card/${this.active.id}/video"><label class="btn ghost inline-video-label">ویدئوی جزئیات<input type="file" name="video_file" accept="video/mp4,video/webm,video/quicktime,video/x-m4v" hidden></label><button type="submit" class="btn primary">آپلود ویدئو</button></form>`:'';
    bar.innerHTML=`<span>این بخش در حالت ویرایش است.</span>${videoForm}<div><button type="button" class="btn primary inline-local-save">ذخیره</button><button type="button" class="btn ghost inline-local-cancel">انصراف</button></div>`;
    root.insertBefore(bar,root.firstChild);
    const fileInput=bar.querySelector('.inline-video-upload input[type=file]');
    const fileLabel=bar.querySelector('.inline-video-label');
    if(fileInput&&fileLabel){fileInput.addEventListener('change',()=>{const name=fileInput.files?.[0]?.name||'ویدئوی جزئیات';fileLabel.childNodes[0].textContent=name+' ';});}
    bar.querySelector('.inline-local-save').onclick=()=>mode==='section'?this.saveSection():this.saveEntity();
    bar.querySelector('.inline-local-cancel').onclick=()=>mode==='section'?this.cancelSection():this.cancelEntity();
  },
  async enterSection(id){
    if(this.active){if(this.active.type==='section')this.cancelSection();else this.cancelEntity()}
    const iframe=document.getElementById('sitePreview');if(!iframe)return;
    const r=await fetch('/admin/api/section/'+id);if(!r.ok)return;const s=await r.json();
    this.active={type:'section',id:s.id,pageId:window.PAGE_ID,section:s,pending:[],iframe};
    iframe.contentWindow.postMessage({type:'enter-inline-section',id:s.id,key:s.section_key},'*');
  },
  async fieldFromPreview(d){
    if(!this.active)return;
    if(d.kind==='solution-link'){this.openSolutionPicker(d);return;}
    const target=d.cardId?{kind:'card',id:+d.cardId}:d.teamId?{kind:'team',id:+d.teamId}:{kind:d.field?.startsWith('__inline:')?'section-inline':'section',id:this.active.id};
    let rawValue=d.html||'';
    // IMPORTANT: never use the HTML currently visible in the preview as the
    // editor source. The preview has already passed through the final marker
    // compiler. Re-open the original stored value directly from the API.
    if(d.kind==='text'){
      try{
        let url='',key=d.field;
        if(target.kind==='section'){
          url='/admin/api/section/'+target.id;
        }else if(target.kind==='section-inline'){
          url='/admin/api/section-inline/'+target.id;
        }else if(target.kind==='card'){
          url='/admin/api/card/'+target.id;
        }else if(target.kind==='team'){
          url='/admin/api/team/'+target.id;
        }
        const r=await fetch(url,{headers:{'X-Requested-With':'XMLHttpRequest'}});
        if(r.ok){
          const data=await r.json();
          if(target.kind==='section-inline'){
            const obj=(data.inline_json&&typeof data.inline_json==='object')?data.inline_json:{};
            rawValue=obj[key] ?? rawValue;
          }else{
            rawValue=data[key] ?? rawValue;
          }
        }
      }catch(e){}
    }
    this.modalState={target,field:d.field,kind:d.kind,html:rawValue,src:d.src||'',sectionId:d.sectionId||this.active.id,cardId:d.cardId||null,teamId:d.teamId||null};
    if(d.kind==='text'){
      const m=this.ensureModal();m.querySelector('#inlineFieldTitle').textContent='ویرایش متن';const ed=m.querySelector('#inlineTextEditor');setRichEditorContent(ed,rawValue);bindRichEditor(ed);m.classList.add('open');setTimeout(()=>{ed.focus();rememberEditorSelection(ed);this.liveModalPreview();},0);
    }else{if(d.kind==='icon')openAssetPicker('icon');else if(d.kind==='model'||target.kind==='section'||target.kind==='section-inline')openAssetPicker('page-media');else openAssetPicker('image')}
  },
  openSolutionPicker(d){
    const m=this.ensureModal();m.querySelector('#inlineFieldTitle').textContent='انتخاب راهکار برای این سناریو';
    const ed=m.querySelector('#inlineTextEditor');ed.contentEditable='false';ed.innerHTML='<div class="solution-picker-list">در حال دریافت راهکارها...</div>';
    this.modalState={target:{kind:'card',id:+d.cardId},field:'link',kind:'solution-link',sectionId:d.sectionId,cardId:+d.cardId};m.classList.add('open');
    fetch('/admin/api/solution-links').then(r=>r.json()).then(items=>{const list=m.querySelector('.solution-picker-list');list.innerHTML=items.map(x=>`<button type="button" class="solution-choice" data-id="${x.id}" data-url="${x.url}">${x.title}</button>`).join('')||'<p>راهکاری ثبت نشده است.</p>';list.querySelectorAll('.solution-choice').forEach(b=>b.onclick=()=>{this.pendingFor(this.modalState.target,'link',b.dataset.url);this.active.iframe?.contentWindow.postMessage({type:'inline-asset-preview',kind:'solution-link',sectionId:this.modalState.sectionId,cardId:this.modalState.cardId,field:'link',url:b.dataset.url,solutionTitle:b.textContent},'*');this.closeFieldModal();})});
  },
  applyLocalPreview(st,payload){
    if(this.active?.type==='entity'){
      const root=this.active.root;
      let el=root?.querySelector('[data-entity-field="'+CSS.escape(st.field)+'"]')||root?.querySelector('[data-inline-key="'+CSS.escape(st.field)+'"]');
      if(!el){if(st.field==='title'||st.field==='name')el=root?.querySelector('h2,h3');else if(['short_desc','role','bio'].includes(st.field))el=[...root.querySelectorAll('p')].find(x=>!x.classList.contains('muted'))||root?.querySelector('p');else if(st.field==='image')el=root?.querySelector('img')}
      if(payload.html!=null&&el){el.innerHTML=payload.html;el.dataset.livePreview='1';}
      if(payload.url&&el?.tagName==='IMG')el.src=payload.url;
    }else this.active?.iframe?.contentWindow.postMessage(Object.assign({type:payload.html!=null?'inline-text-preview':'inline-asset-preview',sectionId:st.sectionId,cardId:st.cardId,teamId:st.teamId,field:st.field},payload),'*');
  },
  assetSelected(a){if(!this.modalState)return;const st=this.modalState;const value=a.kind==='model'?'model:'+a.filename:a.filename;this.pendingFor(st.target,st.field,value);this.applyLocalPreview(st,{url:a.url,kind:a.kind,assetKind:a.kind,backgroundUrl:a.background_url||'',backgroundWidth:a.background_width||0,backgroundHeight:a.background_height||0});this.modalState=null;},
  pendingFor(target,field,value){if(!this.active)return;let x=this.active.pending.find(x=>x.kind===target.kind&&x.id===target.id&&x.field===field);if(x)x.value=value;else this.active.pending.push({kind:target.kind,id:target.id,field,value});},
  liveModalPreview(){if(!this.modalState)return;const ed=this.modal?.querySelector('#inlineTextEditor');if(!ed)return;const v=serializeRichEditor(ed);this.applyLocalPreview(this.modalState,{html:richPreviewHtml(v)});},
  saveFieldModal(){if(!this.modalState)return;const st=this.modalState;if(st.kind==='solution-link'){this.closeFieldModal();return}const v=serializeRichEditor(this.modal.querySelector('#inlineTextEditor'));this.pendingFor(st.target,st.field,v);this.applyLocalPreview(st,{html:richPreviewHtml(v)});this.closeFieldModal();},
  closeFieldModal(){if(this.modal){this.modal.classList.remove('open');const ed=this.modal.querySelector('#inlineTextEditor');ed.contentEditable='true';}this.modalState=null;},
  async saveSection(){if(!this.active)return;const a=this.active;const r=await fetch('/admin/api/inline-save',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},body:JSON.stringify({changes:a.pending||[]})});if(!r.ok)return; a.iframe?.contentWindow.postMessage({type:'exit-inline-section'},'*');a.iframe?.contentWindow.location.reload();this.active=null;},
  cancelSection(){if(!this.active)return;const a=this.active;a.iframe?.contentWindow.postMessage({type:'exit-inline-section'},'*');a.iframe?.contentWindow.location.reload();this.closeFieldModal();this.active=null;},
  async refreshInlineSection(){if(!this.active)return;const a=this.active;const iframe=a.iframe;const sectionId=a.id;const key=a.section?.section_key||'';const onload=()=>{iframe.removeEventListener('load',onload);setTimeout(()=>iframe.contentWindow.postMessage({type:'enter-inline-section',id:sectionId,key},'*'),30)};iframe.addEventListener('load',onload);iframe.contentWindow.location.reload();},
  async addScenario(cardType){if(!this.active||this.active.type!=='section')return;const r=await fetch('/admin/api/scenario/create',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},body:JSON.stringify({card_type:cardType})});if(!r.ok){alert('افزودن کارت سناریو انجام نشد.');return;}await this.refreshInlineSection();},
  async deleteScenario(cardId,cardType){if(!this.active||this.active.type!=='section')return;const r=await fetch('/admin/api/scenario/'+encodeURIComponent(cardId)+'/delete',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},body:JSON.stringify({card_type:cardType})});if(!r.ok){alert('حذف کارت سناریو انجام نشد.');return;}await this.refreshInlineSection();},
  bindCollections(){document.querySelectorAll('.card-inline-edit').forEach(b=>b.onclick=()=>this.enterEntity('card',+b.dataset.cardId,b.closest('.admin-card-preview')));document.querySelectorAll('.entity-inline-edit').forEach(b=>b.onclick=()=>this.enterEntity(b.dataset.entityType,+b.dataset.entityId,b.closest('.entity-preview-card')))},
  async enterEntity(type,id,root){if(this.active){if(this.active.type==='section')this.cancelSection();else this.cancelEntity()}this.active={type,id,root,pending:[]};root.classList.add('inline-editing');this.annotateEntity(root,type,id);this.showLocalActions(root,'entity')},
  annotateEntity(root,type,id){root.querySelectorAll('.inline-edit-icon').forEach(x=>x.remove());const collection=root.closest('[data-card-collection]')?.dataset.cardCollection;const fields=type==='team'?{name:'text',role:'text',bio:'text',image:'image'}:(collection==='capability'?{title:'text',short_desc:'text',icon:'icon'}:{title:'text',subtitle:'text',short_desc:'text',full_desc:'text',image:'image',icon:'icon',tag:'text',link:'text',video:'text'});Object.entries(fields).forEach(([field,kind])=>{let el=root.querySelector('[data-entity-field="'+field+'"]');if(!el){if(field==='title')el=root.querySelector('h2,h3');else if(field==='short_desc')el=root.querySelector('p');else if(field==='image')el=root.querySelector('img')}if(el)this.addEntityButton(el,kind,field,id,type)});},
  addEntityButton(el,kind,field,id,type){if(el.dataset.inlineBound)return;el.dataset.inlineBound='1';const b=document.createElement('button');b.type='button';b.className='inline-edit-icon';b.textContent=kind==='text'?'✎':kind==='image'?'▧':'◈';b.title=kind==='text'?'ویرایش متن':kind==='image'?'انتخاب تصویر':kind==='model'?'انتخاب مدل سه‌بعدی':'انتخاب آیکون';b.onclick=e=>{e.preventDefault();e.stopPropagation();this.fieldFromPreview({kind,field,cardId:type==='card'?id:null,teamId:type==='team'?id:null,sectionId:null,html:kind==='text'?el.innerHTML:'',src:kind!=='text'?el.getAttribute('src'):''})};el.parentElement.style.position=el.parentElement.style.position||'relative';el.insertAdjacentElement('afterend',b)},
  cancelEntity(){if(!this.active)return;location.reload();},
  async saveEntity(){if(!this.active)return;const a=this.active;const r=await fetch('/admin/api/inline-save',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},body:JSON.stringify({changes:a.pending||[]})});if(!r.ok){alert('ذخیره تغییرات انجام نشد.');return;}location.reload();},
  reorderFromPreview(d){if(!this.active)return;this.active.pending=this.active.pending.filter(x=>x.kind!=='reorder');this.active.pending.push({kind:'reorder',reorder_kind:d.kind,card_type:d.card_type,ids:d.ids})}
};
window.InlineAdmin=InlineAdmin;
window.addEventListener('message',e=>{if(e.data?.type==='edit-section')InlineAdmin.enterSection(e.data.id);if(e.data?.type==='inline-field')InlineAdmin.fieldFromPreview(e.data);if(e.data?.type==='inline-reorder')InlineAdmin.reorderFromPreview(e.data);if(e.data?.type==='inline-save-request')InlineAdmin.saveSection();if(e.data?.type==='inline-cancel-request')InlineAdmin.cancelSection();if(e.data?.type==='add-scenario')InlineAdmin.addScenario(e.data.cardType);if(e.data?.type==='delete-scenario'&&e.data.cardId)InlineAdmin.deleteScenario(e.data.cardId,e.data.cardType);});

function initSortableLists(){document.querySelectorAll('.sortable-list').forEach(list=>{list.querySelectorAll('.draggable-row .drag-handle').forEach(handle=>handle.addEventListener('pointerdown',e=>startPointerSort(e,list,handle.closest('.draggable-row'))))})}
let activePointerSort=null;function startPointerSort(e,list,row){if(e.button!==undefined&&e.button!==0)return;e.preventDefault();if(activePointerSort)return;const rect=row.getBoundingClientRect(),placeholder=document.createElement('div');placeholder.className='drag-placeholder';placeholder.style.height=rect.height+'px';placeholder.style.width=rect.width+'px';list.replaceChild(placeholder,row);row.classList.add('dragging');activePointerSort={list,row,placeholder,moved:false,axis:list.id==='footerColumns'?'x':'y',startX:e.clientX,startY:e.clientY};window.addEventListener('pointermove',pointerSortMove,{passive:false});window.addEventListener('pointerup',pointerSortEnd,{once:true});window.addEventListener('pointercancel',pointerSortEnd,{once:true})}
function pointerSortMove(e){const st=activePointerSort;if(!st)return;e.preventDefault();const d=st.axis==='x'?Math.abs(e.clientX-st.startX):Math.abs(e.clientY-st.startY);if(d>4)st.moved=true;const target=document.elementFromPoint(e.clientX,e.clientY)?.closest('.draggable-row');if(!target||target.parentElement!==st.list)return;const rect=target.getBoundingClientRect(),before=st.axis==='x'?e.clientX<rect.left+rect.width/2:e.clientY<rect.top+rect.height/2;if(before)st.list.insertBefore(st.placeholder,target);else st.list.insertBefore(st.placeholder,target.nextSibling)}
function pointerSortEnd(){const st=activePointerSort;if(!st)return;window.removeEventListener('pointermove',pointerSortMove);st.row.classList.remove('dragging');st.list.replaceChild(st.row,st.placeholder);const moved=st.moved;activePointerSort=null;if(moved)persistSortable(st.list)}
function persistSortable(list){let endpoint=list.dataset.sortEndpoint,payload={ids:[...list.querySelectorAll('.draggable-row')].map(x=>x.dataset.id)};if(list.dataset.cardType)payload.card_type=list.dataset.cardType;if(list.dataset.location){endpoint='/admin/menus/reorder';payload.location=list.dataset.location}else if(list.dataset.pageId){endpoint='/admin/page/'+list.dataset.pageId+'/reorder'}else if(list.id==='projectsList'){endpoint='/admin/projects/reorder'}else if(list.id==='teamList'){endpoint='/admin/team/reorder'}else if(!endpoint)return;fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},body:JSON.stringify(payload)}).then(r=>{if(r.ok)location.reload();else alert('ذخیره ترتیب انجام نشد.')})}
document.addEventListener('DOMContentLoaded',()=>{initSortableLists();InlineAdmin.bindCollections()});
function togglePassword(btn){const input=btn?.parentElement?.querySelector('input');if(!input)return;input.type=input.type==='password'?'text':'password';btn.setAttribute('aria-label',input.type==='password'?'نمایش رمز':'مخفی کردن رمز')}

function applyThemedIcons(root=document){
  const color=getComputedStyle(document.documentElement).getPropertyValue('--icon-color').trim() || getComputedStyle(document.documentElement).getPropertyValue('--primary').trim() || getComputedStyle(document.documentElement).getPropertyValue('--admin-primary').trim() || '#B6E23A';
  const imgs=[...(root.querySelectorAll?.('img.icon-clean')||[])];
  imgs.forEach(img=>{
    const src=img.currentSrc||img.src||img.getAttribute('src');
    if(!src || !/\.svg(?:[?#].*)?$/i.test(src)) return;
    let wrap=img.closest('.themed-icon-wrap');
    if(!wrap){
      wrap=document.createElement('span');
      wrap.className='themed-icon-wrap';
      const cs=getComputedStyle(img);
      wrap.style.display='inline-block';
      wrap.style.width=cs.width;
      wrap.style.height=cs.height;
      wrap.style.flex='0 0 auto';
      wrap.style.position='relative';
      img.parentNode.insertBefore(wrap,img);
      wrap.appendChild(img);
      img.dataset.themedIcon='1';
      img.style.setProperty('opacity','0','important');
      img.style.setProperty('position','absolute','important');
      img.style.setProperty('inset','0','important');
      img.style.setProperty('width','100%','important');
      img.style.setProperty('height','100%','important');
      img.style.setProperty('pointer-events','none','important');
    }
    wrap.style.setProperty('background-color',color,'important');
    wrap.style.setProperty('-webkit-mask-image',`url("${src}")`,'important');
    wrap.style.setProperty('mask-image',`url("${src}")`,'important');
    wrap.style.setProperty('-webkit-mask-repeat','no-repeat','important');
    wrap.style.setProperty('mask-repeat','no-repeat','important');
    wrap.style.setProperty('-webkit-mask-position','center','important');
    wrap.style.setProperty('mask-position','center','important');
    wrap.style.setProperty('-webkit-mask-size','contain','important');
    wrap.style.setProperty('mask-size','contain','important');
  });
}

function initThemedIconObserver(){
  applyThemedIcons();
  const observer=new MutationObserver(mutations=>{
    let needs=false;
    for(const m of mutations){
      if(m.type==='childList' || (m.type==='attributes' && m.attributeName==='src')){needs=true;break;}
    }
    if(needs) requestAnimationFrame(()=>applyThemedIcons());
  });
  observer.observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeFilter:['src']});
}
document.addEventListener('DOMContentLoaded',initThemedIconObserver);


function initLoopingVideoImageSlots(){
  const convert=(root=document)=>{
    const candidates=[];
    if(root.matches?.('img')) candidates.push(root);
    candidates.push(...(root.querySelectorAll?.('img[src],img[srcset]')||[]));
    candidates.forEach(img=>{
      const src=img.getAttribute('src')||img.currentSrc||'';
      if(!/\.(mp4|webm|ogv|ogg|mov|m4v)(?:[?#].*)?$/i.test(src) || img.dataset.loopVideoConverted) return;
      const video=document.createElement('video');
      [...img.attributes].forEach(attr=>{
        if(!['src','srcset','alt','loading','decoding'].includes(attr.name)) video.setAttribute(attr.name,attr.value);
      });
      video.src=src;
      video.autoplay=true; video.muted=true; video.loop=true; video.playsInline=true;
      video.setAttribute('aria-label',img.getAttribute('alt')||'ویدئوی تکرارشونده');
      video.dataset.loopVideoConverted='1';
      img.replaceWith(video);
      const play=video.play(); if(play?.catch) play.catch(()=>{});
    });
  };
  convert();
  const observer=new MutationObserver(records=>{
    records.forEach(record=>{
      record.addedNodes.forEach(node=>{if(node.nodeType===1) convert(node);});
      if(record.type==='attributes' && record.target.matches?.('img')) convert(record.target);
    });
  });
  observer.observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeFilter:['src','srcset']});
}
document.addEventListener('DOMContentLoaded',initLoopingVideoImageSlots);
