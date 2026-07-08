#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档编辑器 HTML：预览、主题 CSS/JS、渲染缓存。"""
import os
import json

import doc_paths as dpaths
from doc_paths import DocDir, ReadJson, WriteJson
from docx_parser import *  # noqa: F403

_oEditorHtmlCache = {}
_nEditorCacheMax = 10


def _PparaCommentsMap(vcomments, sstatus=None):
    opara_comments = {}
    for oc in vcomments or []:
        if sstatus and oc.get("status") != sstatus:
            continue
        nidx = oc.get("para_index", -1)
        if nidx >= 0:
            opara_comments.setdefault(nidx, []).append(oc)
    return opara_comments


def BuildPreview(sdocid, vcomments=None):
    from docx import Document
    sdir = DocDir(sdocid)
    scurrent = os.path.join(sdir, "current.docx")
    if vcomments is None:
        vcomments = ReadJson(os.path.join(sdir, "comments.json"), {"items": []}).get("items", [])
    odoc = Document(scurrent)
    oimgurls = _LoadImageUrls(sdocid, scurrent)
    othemes = _LoadThemeFonts(scurrent)
    sbody = _BuildDocumentBodyHtml(
        odoc, oimgurls,
        _PparaCommentsMap(vcomments),
        _PparaCommentsMap(vcomments, "pending"),
        False, othemes,
    )
    shtml = '<div class="docpreview">%s</div>' % sbody
    with open(os.path.join(sdir, "preview.html"), "w", encoding="utf-8") as f:
        f.write(shtml)
    return shtml


_EDITOR_THEME_CSS = {
    "fresh": {
        "workspace": "#e6ebe6", "page": "#f8f9f7", "text": "#3f4a44",
        "focus_bg": "rgba(122,148,136,.1)", "focus_border": "#7a9488",
        "comment_bg": "rgba(184,168,120,.14)", "comment_border": "#b8a878",
        "status_bg": "rgba(248,249,247,.94)", "status_border": "rgba(122,148,136,.22)",
        "shadow": "rgba(63,74,68,.08)",
    },
    "girly": {
        "workspace": "#e8e2de", "page": "#fffcfb", "text": "#4a3f47",
        "focus_bg": "rgba(201,120,154,.1)", "focus_border": "#c9789a",
        "comment_bg": "rgba(232,184,109,.18)", "comment_border": "#e8b86d",
        "status_bg": "rgba(255,252,251,.92)", "status_border": "rgba(201,120,154,.25)",
        "shadow": "rgba(74,63,71,.12)",
    },
    "boyish": {
        "workspace": "#d0d8e4", "page": "#ffffff", "text": "#1e3a5f",
        "focus_bg": "rgba(61,125,214,.1)", "focus_border": "#3d7dd6",
        "comment_bg": "rgba(232,160,64,.16)", "comment_border": "#e8a040",
        "status_bg": "rgba(255,255,255,.94)", "status_border": "rgba(61,125,214,.28)",
        "shadow": "rgba(30,58,95,.12)",
    },
    "cool": {
        "workspace": "#2a3038", "page": "#1c2330", "text": "#e6edf3",
        "focus_bg": "rgba(0,212,255,.12)", "focus_border": "#00d4ff",
        "comment_bg": "rgba(251,191,36,.14)", "comment_border": "#fbbf24",
        "status_bg": "rgba(22,27,34,.92)", "status_border": "rgba(0,212,255,.28)",
        "shadow": "rgba(0,0,0,.35)",
    },
}


def GetEditorCss(stheme="girly"):
    otheme = _EDITOR_THEME_CSS.get(stheme) or _EDITOR_THEME_CSS["girly"]
    return (
        "*{box-sizing:border-box}"
        "html,body{margin:0;height:100%%;overflow:hidden;background:%(workspace)s;font-family:"
        '"PingFang SC","Microsoft YaHei","SimSun",serif;display:flex;flex-direction:column}'
        ".fmtshell{position:fixed;top:0;left:0;right:0;z-index:30;transition:transform .2s ease;will-change:transform}"
        ".fmtshell.fmt-hidden{transform:translateY(-100%%)}"
        ".fmtshell.fmt-hidden.fmt-open,.fmtshell.fmt-hidden:hover{transform:translateY(0)}"
        ".fmtpeek{position:fixed;top:0;left:0;right:0;height:10px;z-index:29;display:none}"
        ".fmtpeek.show{display:block}"
        ".fmtbar{display:flex;align-items:center;gap:6px;flex-wrap:wrap;"
        "padding:6px 12px;background:%(status_bg)s;border-bottom:1px solid %(status_border)s;"
        "box-shadow:0 4px 16px %(shadow)s;backdrop-filter:blur(8px)}"
        ".fmtbar .grp{display:flex;align-items:center;gap:4px;padding-right:8px;margin-right:4px;"
        "border-right:1px solid %(status_border)s}"
        ".fmtbar .grp:last-child{border-right:none;margin-right:0;padding-right:0}"
        ".fmtbtn{min-width:30px;height:30px;padding:0 8px;border-radius:8px;border:1px solid %(status_border)s;"
        "background:%(page)s;color:%(text)s;font-size:13px;font-weight:700;cursor:pointer;line-height:1}"
        ".fmtbtn:hover{border-color:%(focus_border)s;color:%(focus_border)s}"
        ".fmtbtn.on{background:%(focus_bg)s;border-color:%(focus_border)s;color:%(focus_border)s}"
        ".fmtbtn.i{font-style:italic;font-family:Georgia,serif}"
        ".fmtbtn.u{text-decoration:underline}"
        ".fmtselect{height:30px;padding:0 8px;border-radius:8px;border:1px solid %(status_border)s;"
        "background:%(page)s;color:%(text)s;font-size:12px;max-width:118px}"
        ".fmtcolor{width:30px;height:30px;padding:2px;border-radius:8px;border:1px solid %(status_border)s;"
        "background:%(page)s;cursor:pointer}"
        ".docworkspace{flex:1;min-height:0;overflow-y:auto;padding:44px 16px 48px}"
        ".docpage{max-width:794px;margin:0 auto;background:%(page)s;color:%(text)s;"
        "min-height:1123px;padding:72px 84px;box-shadow:0 8px 32px %(shadow)s;"
        "border-radius:4px;font-size:12pt;line-height:1.5}"
        ".parablock{margin:0 0 10px}"
        ".docpage .docpara{font-size:inherit;line-height:inherit}"
        ".cmtmarks{line-height:1.2;margin-bottom:2px;user-select:none}"
        ".docpara{margin:0;padding:2px 4px;border-radius:6px;outline:none;position:relative;min-height:1.4em;"
        "white-space:pre-wrap;-webkit-user-select:text;user-select:text}"
        ".docpara:focus,.docpara.selected{background:%(focus_bg)s;box-shadow:inset 0 0 0 2px %(focus_border)s}"
        ".docpara.has-comment{background:%(comment_bg)s;border-left:3px solid %(comment_border)s;"
        "padding-left:8px;margin-left:-4px}"
        ".docpara.has-image{min-height:24px}"
        ".imgwrap{display:inline-block;max-width:100%%;vertical-align:middle}"
        ".docimg{max-width:100%%;height:auto;display:block;margin:10px auto;border-radius:2px}"
        ".doctable{width:100%%;border-collapse:collapse;margin:12px 0;font-size:14px}"
        ".doctable td,.doctable th{border:1px solid #ccc;padding:6px 8px;vertical-align:top}"
        ".cmtmark{cursor:pointer;margin-right:6px;user-select:none}"
        ".docstatus{position:fixed;bottom:12px;right:16px;font-size:12px;color:%(text)s;"
        "background:%(status_bg)s;border:1px solid %(status_border)s;padding:6px 14px;"
        "border-radius:999px;box-shadow:0 4px 16px %(shadow)s;display:none}"
        ".docstatus.show{display:block}"
    ) % otheme

_EDITOR_JS = """
const DOC_ID=%(docid)s;
let selectedPara=-1,selectedComment=null,saving=false,activePara=null,savedRange=null;
function notify(o){try{parent.postMessage(Object.assign({source:'paper-doc-editor'},o),'*')}catch(e){}}
function paraFromNode(n){
  while(n){if(n.nodeType===1&&n.classList&&n.classList.contains('docpara-editable'))return n;n=n.parentNode}
  return null;
}
function touchPara(el,scroll){
  if(!el)return;
  document.querySelectorAll('.docpara.selected').forEach(p=>p.classList.remove('selected'));
  el.classList.add('selected');
  activePara=el;
  selectedPara=parseInt(el.dataset.para,10);
  if(scroll!==false)el.scrollIntoView({behavior:'smooth',block:'center'});
}
function selectPara(el,scroll){
  touchPara(el,scroll);
  notify({type:'doc-para',para:selectedPara,plain:el.dataset.plain||'',hasImage:el.classList.contains('has-image')});
  updateFmtUi();
}
function saveSelection(){
  const osel=window.getSelection();
  if(!osel||!osel.rangeCount)return;
  const orange=osel.getRangeAt(0);
  const opara=paraFromNode(orange.commonAncestorContainer);
  if(!opara)return;
  activePara=opara;
  touchPara(opara,false);
  if(!orange.collapsed)savedRange=orange.cloneRange();
}
function restoreSavedSelection(){
  if(!savedRange||!activePara||!document.contains(activePara))return false;
  try{
    activePara.focus({preventScroll:true});
    const osel=window.getSelection();
    osel.removeAllRanges();
    osel.addRange(savedRange);
    return !savedRange.collapsed;
  }catch(e){savedRange=null;return false}
}
function currentSelectionRange(){
  const osel=window.getSelection();
  if(!osel||!osel.rangeCount)return null;
  const orange=osel.getRangeAt(0);
  if(orange.collapsed)return savedRange&&!savedRange.collapsed?savedRange:null;
  return orange;
}
function ensureFmtReady(){
  if(restoreSavedSelection())return activePara;
  if(activePara&&document.contains(activePara)){
    activePara.focus({preventScroll:true});
    return activePara;
  }
  const op=document.querySelector('.docpara-editable.selected')||document.querySelector('.docpara-editable');
  if(op){touchPara(op,false);op.focus({preventScroll:true});return op}
  return null;
}
function needSelection(){
  const orange=currentSelectionRange();
  if(orange&&!orange.collapsed)return orange;
  showStatus('请先框选要排版的文字');
  return null;
}
function wrapRangeStyle(orange,sstyle){
  if(!orange||orange.collapsed)return false;
  const ospan=document.createElement('span');
  ospan.setAttribute('style',sstyle);
  try{orange.surroundContents(ospan)}catch(e){
    const sfrag=orange.extractContents();
    ospan.appendChild(sfrag);
    orange.insertNode(ospan);
  }
  const osel=window.getSelection();
  osel.removeAllRanges();
  const nr=document.createRange();
  nr.selectNodeContents(ospan);
  osel.addRange(nr);
  savedRange=nr.cloneRange();
  return true;
}
function paraPlainText(el){
  const s=(el.innerText||'').replace(/\\uFE0F/g,'').replace(/📝/g,'').replace(/\\s+$/,'');
  return s;
}
function paraHtml(el){
  const oclone=el.cloneNode(true);
  oclone.querySelectorAll('.cmtmark,.imgwrap').forEach(n=>n.remove());
  return oclone.innerHTML.trim();
}
function paraBlockStyle(el){
  return (el.getAttribute('style')||el.dataset.pstyle||'').trim();
}
function initParaState(el){
  if(!el.dataset.html)el.dataset.html=paraHtml(el);
  if(!el.dataset.plain)el.dataset.plain=paraPlainText(el);
  if(!el.dataset.pstyle)el.dataset.pstyle=paraBlockStyle(el);
}
function paraSnapshot(el){return {h:el.innerHTML,s:el.getAttribute('style')||''}}
function paraRestore(el,snap){
  el._restoring=true;
  el.innerHTML=snap.h;
  if(snap.s)el.setAttribute('style',snap.s);else el.removeAttribute('style');
  el._restoring=false;
}
function ensureHist(el){if(el&&!el._undo){el._undo=[paraSnapshot(el)];el._redo=[]}}
function recordChange(el){
  if(!el)return;
  ensureHist(el);
  const snap=paraSnapshot(el);
  const last=el._undo[el._undo.length-1];
  if(last&&last.h===snap.h&&last.s===snap.s)return;
  el._undo.push(snap);
  if(el._undo.length>150)el._undo.shift();
  el._redo=[];
}
function undoPara(el){
  if(!el)return false;
  ensureHist(el);
  if(el._undo.length<2)return false;
  const cur=el._undo.pop();
  el._redo.push(cur);
  paraRestore(el,el._undo[el._undo.length-1]);
  return true;
}
function redoPara(el){
  if(!el||!el._redo||!el._redo.length)return false;
  const snap=el._redo.pop();
  el._undo.push(snap);
  paraRestore(el,snap);
  return true;
}
function activeEditable(){
  if(activePara&&document.contains(activePara))return activePara;
  const sel=window.getSelection();
  if(sel&&sel.rangeCount){const p=paraFromNode(sel.getRangeAt(0).commonAncestorContainer);if(p)return p}
  return document.querySelector('.docpara-editable.selected')||document.querySelector('.docpara-editable');
}
function undoActive(){
  const el=activeEditable();if(!el)return;
  if(undoPara(el)){touchPara(el,false);el.focus({preventScroll:true});savePara(el);showStatus('已撤销')}
  else showStatus('没有可撤销的修改');
}
function redoActive(){
  const el=activeEditable();if(!el)return;
  if(redoPara(el)){touchPara(el,false);el.focus({preventScroll:true});savePara(el);showStatus('已重做')}
  else showStatus('没有可重做的修改');
}
let typingTimer=0,typingEl=null;
function scheduleTypingSnap(el){
  typingEl=el;
  clearTimeout(typingTimer);
  typingTimer=setTimeout(()=>{if(typingEl)recordChange(typingEl)},350);
}
function commitFmt(el){if(!el)return;recordChange(el);savePara(el);}
function targetParas(){
  const all=[...document.querySelectorAll('.docpara-editable')];
  const sel=window.getSelection();
  if(sel&&sel.rangeCount&&!sel.getRangeAt(0).collapsed){
    const r=sel.getRangeAt(0);
    const within=all.filter(p=>{try{return r.intersectsNode(p)}catch(e){return false}});
    if(within.length)return within;
  }
  const op=ensureFmtReady();return op?[op]:[];
}
async function savePara(el){
  if(saving)return;
  const n=parseInt(el.dataset.para,10);
  const stext=paraPlainText(el);
  const shtml=paraHtml(el);
  const spstyle=paraBlockStyle(el);
  if(stext===(el.dataset.plain||'')&&shtml===(el.dataset.html||'')&&spstyle===(el.dataset.pstyle||''))return;
  saving=true;showStatus('正在保存…');
  try{
    const obody={id:DOC_ID,para_index:n,text:stext,html:shtml,para_style:spstyle};
    if(selectedComment)obody.comment_id=selectedComment;
    await parent.Api('/api/docs/edit',obody);
    el.dataset.plain=stext;
    el.dataset.html=shtml;
    el.dataset.pstyle=spstyle;
    notify({type:'doc-saved',para:n,commentId:selectedComment||null});
    showStatus('已保存');
  }catch(e){showStatus('保存失败');notify({type:'doc-error',msg:e.message});}
  saving=false;
}
function showStatus(s){const el=document.getElementById('docstatus');el.textContent=s;el.classList.add('show');setTimeout(()=>el.classList.remove('show'),1800);}
function runFmt(cmd,val){
  const op=ensureFmtReady();if(!op)return;
  const orange=needSelection();if(!orange)return;
  ensureHist(op);
  const osel=window.getSelection();
  osel.removeAllRanges();
  osel.addRange(orange);
  try{document.execCommand('styleWithCSS',false,true)}catch(e){}
  document.execCommand(cmd,false,val||null);
  saveSelection();
  commitFmt(op);
  updateFmtUi();
}
function applyFontName(sname){
  if(!sname)return;
  const op=ensureFmtReady();if(!op)return;
  const orange=needSelection();if(!orange)return;
  ensureHist(op);
  const osel=window.getSelection();
  osel.removeAllRanges();
  osel.addRange(orange);
  wrapRangeStyle(orange,"font-family:'"+sname.replace(/'/g,"")+"'");
  saveSelection();
  commitFmt(op);
  updateFmtUi();
}
function applyFontSize(spt){
  if(!spt)return;
  const op=ensureFmtReady();if(!op)return;
  const orange=needSelection();if(!orange)return;
  ensureHist(op);
  const osel=window.getSelection();
  osel.removeAllRanges();
  osel.addRange(orange);
  wrapRangeStyle(orange,'font-size:'+spt+'pt');
  saveSelection();
  commitFmt(op);
  updateFmtUi();
}
function applyColor(scolor){
  if(!scolor)return;
  const op=ensureFmtReady();if(!op)return;
  const orange=needSelection();if(!orange)return;
  ensureHist(op);
  const osel=window.getSelection();
  osel.removeAllRanges();
  osel.addRange(orange);
  try{document.execCommand('styleWithCSS',false,true)}catch(e){}
  if(!document.execCommand('foreColor',false,scolor))wrapRangeStyle(orange,'color:'+scolor);
  saveSelection();
  commitFmt(op);
  updateFmtUi();
}
function parsePtStyle(sstyle,skey){
  if(!sstyle)return 0;
  const sm=sstyle.match(new RegExp(skey+'\\s*:\\s*([\\d.]+)pt','i'));
  return sm?parseFloat(sm[1]):0;
}
function mergeParaStyle(el,patch){
  const cur=(el.getAttribute('style')||el.dataset.pstyle||'').trim();
  const omap={};
  cur.split(';').forEach(sp=>{
    if(!sp||sp.indexOf(':')<0)return;
    const kv=sp.split(':');
    omap[kv[0].trim().toLowerCase()]=kv.slice(1).join(':').trim();
  });
  Object.keys(patch).forEach(k=>{omap[k.toLowerCase()]=patch[k]});
  const snew=Object.keys(omap).filter(k=>omap[k]!==''&&omap[k]!=null).map(k=>k+':'+omap[k]).join(';');
  el.setAttribute('style',snew);
  return snew;
}
function applyParaAlign(salign){
  const vps=targetParas();if(!vps.length){showStatus('请先点选要排版的段落');return}
  vps.forEach(op=>{ensureHist(op);mergeParaStyle(op,{'text-align':salign});recordChange(op);savePara(op)});
  showStatus('已设置对齐');
}
function applyParaIndent(ndelta){
  const vps=targetParas();if(!vps.length){showStatus('请先点选要排版的段落');return}
  vps.forEach(op=>{
    ensureHist(op);
    const sstyle=op.getAttribute('style')||op.dataset.pstyle||'';
    let nleft=parsePtStyle(sstyle,'margin-left');
    if(!nleft)nleft=parsePtStyle(sstyle,'padding-left');
    nleft=Math.max(0,Math.round((nleft+ndelta)*10)/10);
    mergeParaStyle(op,{'margin-left':nleft?nleft+'pt':'0pt','padding-left':''});
    recordChange(op);savePara(op);
  });
  showStatus(ndelta>0?'已增加缩进':'已减少缩进');
}
function applyLineSpacing(sval){
  const vps=targetParas();if(!vps.length){showStatus('请先点选要排版的段落');return}
  vps.forEach(op=>{ensureHist(op);mergeParaStyle(op,{'line-height':sval});recordChange(op);savePara(op)});
  showStatus('已设置行距');
}
async function flushAllParas(){
  const vels=[...document.querySelectorAll('.docpara-editable')];
  for(const el of vels)await savePara(el);
}
window.flushAllParas=flushAllParas;
async function saveNow(){
  showStatus('正在保存…');
  try{await flushAllParas();showStatus('已保存');}
  catch(e){showStatus('保存失败');}
  notify({type:'doc-flushed'});
}
window.saveNow=saveNow;
function updateFmtUi(){
  const ob=document.getElementById('fmt_bold');
  const oi=document.getElementById('fmt_italic');
  const ou=document.getElementById('fmt_underline');
  let b=false,i=false,u=false;
  try{
    b=document.queryCommandState('bold');
    i=document.queryCommandState('italic');
    u=document.queryCommandState('underline');
  }catch(e){}
  if(ob)ob.classList.toggle('on',b);
  if(oi)oi.classList.toggle('on',i);
  if(ou)ou.classList.toggle('on',u);
}
function InitFmtReveal(){
  const ows=document.querySelector('.docworkspace');
  const osh=document.querySelector('.fmtshell');
  const opk=document.querySelector('.fmtpeek');
  if(!ows||!osh)return;
  let nlast=0,ntimer=0;
  function SetFmtOpen(b){osh.classList.toggle('fmt-open',!!b)}
  function SetFmtHidden(b){
    osh.classList.toggle('fmt-hidden',!!b);
    if(opk)opk.classList.toggle('show',!!b);
    if(!b)SetFmtOpen(false);
  }
  function KeepFmtOpen(){
    if(osh.classList.contains('fmt-hidden'))SetFmtOpen(true);
  }
  ows.addEventListener('scroll',()=>{
    const nst=ows.scrollTop;
    if(nst<=4){SetFmtHidden(false);SetFmtOpen(false);nlast=nst;return}
    if(nst>nlast+5)SetFmtHidden(true);
    else if(nst<nlast-5){SetFmtHidden(true);SetFmtOpen(true)}
    nlast=nst;
  },{passive:true});
  if(opk){
    opk.addEventListener('mouseenter',KeepFmtOpen);
    opk.addEventListener('click',KeepFmtOpen);
  }
  osh.addEventListener('mouseenter',KeepFmtOpen);
  osh.addEventListener('mouseleave',()=>{
    if(osh.querySelector('select:focus,input:focus'))return;
    clearTimeout(ntimer);
    ntimer=setTimeout(()=>{if(ows.scrollTop>4&&!osh.matches(':hover')&&!opk.matches(':hover'))SetFmtOpen(false)},400);
  });
  osh.addEventListener('focusin',KeepFmtOpen);
}
function bindFmtBar(){
  const osh=document.querySelector('.fmtshell');
  const obar=document.querySelector('.fmtbar');
  if(obar){
    obar.addEventListener('mousedown',e=>{
      const stag=(e.target.tagName||'').toUpperCase();
      if(stag==='SELECT'||stag==='INPUT'||stag==='OPTION')return;
      e.preventDefault();
    });
  }
  InitFmtReveal();
  const osave=document.getElementById('fmt_save');if(osave)osave.onclick=saveNow;
  const oundo=document.getElementById('fmt_undo');if(oundo)oundo.onclick=undoActive;
  const oredo=document.getElementById('fmt_redo');if(oredo)oredo.onclick=redoActive;
  document.getElementById('fmt_bold').onclick=()=>runFmt('bold');
  document.getElementById('fmt_italic').onclick=()=>runFmt('italic');
  document.getElementById('fmt_underline').onclick=()=>runFmt('underline');
  document.getElementById('fmt_align_left').onclick=()=>applyParaAlign('left');
  document.getElementById('fmt_align_center').onclick=()=>applyParaAlign('center');
  document.getElementById('fmt_align_right').onclick=()=>applyParaAlign('right');
  document.getElementById('fmt_align_justify').onclick=()=>applyParaAlign('justify');
  document.getElementById('fmt_indent_inc').onclick=()=>applyParaIndent(21);
  document.getElementById('fmt_indent_dec').onclick=()=>applyParaIndent(-21);
  const oline=document.getElementById('fmt_linespace');
  if(oline)oline.addEventListener('change',e=>{const v=e.target.value;if(v)applyLineSpacing(v);e.target.selectedIndex=0});
  const ofont=document.getElementById('fmt_font');
  const osize=document.getElementById('fmt_size');
  const ocolor=document.getElementById('fmt_color');
  [ofont,osize,ocolor].forEach(oel=>{
    if(!oel)return;
    oel.addEventListener('mousedown',saveSelection);
    oel.addEventListener('focus',()=>{if(osh)osh.classList.add('fmt-open')});
  });
  ofont.addEventListener('change',e=>{const v=e.target.value;if(v)applyFontName(v);e.target.selectedIndex=0});
  osize.addEventListener('change',e=>{const v=e.target.value;if(v)applyFontSize(v);e.target.selectedIndex=0});
  ocolor.addEventListener('input',e=>applyColor(e.target.value));
  document.addEventListener('selectionchange',()=>{saveSelection();updateFmtUi()});
}
function insertCitationText(stext){
  const op=ensureFmtReady();
  if(!op){showStatus('请先点击要插入引用的段落');return false}
  op.focus({preventScroll:true});
  let orange=currentSelectionRange();
  if(orange&&!orange.collapsed){
    orange.deleteContents();
    orange.insertNode(document.createTextNode(stext));
    orange.collapse(false);
  }else{
    const osel=window.getSelection();
    if(!osel)return false;
    orange=osel.rangeCount?osel.getRangeAt(0):null;
    if(!orange||!op.contains(orange.commonAncestorContainer)){
      orange=document.createRange();
      orange.selectNodeContents(op);
      orange.collapse(false);
    }
    orange.insertNode(document.createTextNode(stext));
    orange.collapse(false);
    osel.removeAllRanges();
    osel.addRange(orange);
  }
  saveSelection();
  scheduleTypingSnap(op);
  savePara(op);
  showStatus('已插入引用');
  return true;
}
window.insertCitationText=insertCitationText;
window.addEventListener('message',e=>{
  const d=e.data;
  if(!d||d.source!=='paper-helper')return;
  if(d.type==='insert-citation'&&d.text)insertCitationText(d.text);
});
window.focusPara=function(npara,scid){
  selectedComment=scid||null;
  const el=document.getElementById('para-'+npara);
  if(el)selectPara(el);
};
document.querySelectorAll('.docpara-editable').forEach(el=>{
  initParaState(el);
  ensureHist(el);
  el.addEventListener('focus',()=>{ensureHist(el);selectPara(el,false)});
  el.addEventListener('blur',()=>{if(typingEl===el){clearTimeout(typingTimer);recordChange(el);typingEl=null}savePara(el)});
  el.addEventListener('mouseup',saveSelection);
  el.addEventListener('keyup',saveSelection);
  el.addEventListener('input',()=>{if(!el._restoring)scheduleTypingSnap(el)});
  el.addEventListener('keydown',e=>{
    if(e.key!=='Enter'||e.isComposing)return;
    e.preventDefault();
    try{document.execCommand('insertLineBreak')}catch(err){
      document.execCommand('insertHTML',false,'<br>');
    }
    saveSelection();
    scheduleTypingSnap(el);
  });
});
document.addEventListener('keydown',e=>{
  const bmod=e.metaKey||e.ctrlKey;
  if(!bmod)return;
  const sk=(e.key||'').toLowerCase();
  if(sk==='s'){e.preventDefault();saveNow();return}
  if(sk==='z'){e.preventDefault();if(e.shiftKey)redoActive();else undoActive();return}
  if(sk==='y'){e.preventDefault();redoActive();return}
  if(sk==='b'){e.preventDefault();runFmt('bold');return}
  if(sk==='i'){e.preventDefault();runFmt('italic');return}
  if(sk==='u'){e.preventDefault();runFmt('underline');return}
},true);
document.querySelectorAll('.cmtmark').forEach(el=>{
  el.addEventListener('click',e=>{e.stopPropagation();notify({type:'doc-cmt',cid:el.dataset.cid})});
});
bindFmtBar();
notify({type:'doc-ready'});
"""


def _EditorCacheKey(sdocid, stheme):
    scurrent = os.path.join(DocDir(sdocid), "current.docx")
    scomments = os.path.join(DocDir(sdocid), "comments.json")
    if not os.path.isfile(scurrent):
        return ""
    nver = (
        int(os.path.getmtime(scurrent) * 1000),
        os.path.getsize(scurrent),
        int(os.path.getmtime(scomments) * 1000) if os.path.isfile(scomments) else 0,
    )
    return "%s:%s:%s:fmt6" % (sdocid, stheme, nver)


def _TouchEditorCache(skey, shtml):
    global _oEditorHtmlCache
    if skey in _oEditorHtmlCache:
        _oEditorHtmlCache.pop(skey, None)
    _oEditorHtmlCache[skey] = shtml
    while len(_oEditorHtmlCache) > _nEditorCacheMax:
        _oEditorHtmlCache.pop(next(iter(_oEditorHtmlCache)))


def RenderEditorHtml(sdocid, stheme="girly"):
    from docx import Document
    sdir = DocDir(sdocid)
    scurrent = os.path.join(sdir, "current.docx")
    if not os.path.isfile(scurrent):
        raise ValueError("文档不存在")
    vcomments = ReadJson(os.path.join(sdir, "comments.json"), {"items": []}).get("items", [])
    odoc = Document(scurrent)
    oimgurls = _LoadImageUrls(sdocid, scurrent)
    othemes = _LoadThemeFonts(scurrent)
    sbody = _BuildDocumentBodyHtml(
        odoc, oimgurls,
        _PparaCommentsMap(vcomments),
        _PparaCommentsMap(vcomments, "pending"),
        True, othemes,
    )
    sdocid_js = json.dumps(sdocid)
    scss = GetEditorCss(stheme)
    sjs = _EDITOR_JS % {"docid": sdocid_js}
    sfmtbar = (
        '<div class="fmtshell">'
        '<div class="fmtbar">'
        '<div class="grp">'
        '<button type="button" class="fmtbtn" id="fmt_save" title="保存当前文本 (Ctrl/⌘+S)">💾</button>'
        '</div>'
        '<div class="grp">'
        '<button type="button" class="fmtbtn" id="fmt_undo" title="撤销 (Ctrl/⌘+Z)">↶</button>'
        '<button type="button" class="fmtbtn" id="fmt_redo" title="重做 (Ctrl/⌘+Shift+Z)">↷</button>'
        '</div>'
        '<div class="grp">'
        '<button type="button" class="fmtbtn" id="fmt_bold" title="加粗 (Ctrl/⌘+B)">B</button>'
        '<button type="button" class="fmtbtn i" id="fmt_italic" title="倾斜 (Ctrl/⌘+I)">I</button>'
        '<button type="button" class="fmtbtn u" id="fmt_underline" title="下划线 (Ctrl/⌘+U)">U</button>'
        '</div>'
        '<div class="grp">'
        '<select class="fmtselect" id="fmt_font" title="字体">'
        '<option value="">字体</option>'
        '<option value="SimSun">宋体</option>'
        '<option value="SimHei">黑体</option>'
        '<option value="KaiTi">楷体</option>'
        '<option value="FangSong">仿宋</option>'
        '<option value="Microsoft YaHei">微软雅黑</option>'
        '<option value="PingFang SC">苹方</option>'
        '<option value="Times New Roman">Times</option>'
        '<option value="Arial">Arial</option>'
        '</select>'
        '<select class="fmtselect" id="fmt_size" title="字号">'
        '<option value="">字号</option>'
        '<option value="10">10pt</option><option value="11">11pt</option>'
        '<option value="12">12pt</option><option value="14">14pt</option>'
        '<option value="16">16pt</option><option value="18">18pt</option>'
        '<option value="20">20pt</option><option value="22">22pt</option>'
        '<option value="24">24pt</option><option value="28">28pt</option>'
        '<option value="32">32pt</option>'
        '</select>'
        '<input type="color" class="fmtcolor" id="fmt_color" value="#4a3f47" title="文字颜色">'
        '</div>'
        '<div class="grp">'
        '<button type="button" class="fmtbtn" id="fmt_align_left" title="左对齐">⫷</button>'
        '<button type="button" class="fmtbtn" id="fmt_align_center" title="居中">≡</button>'
        '<button type="button" class="fmtbtn" id="fmt_align_right" title="右对齐">⫸</button>'
        '<button type="button" class="fmtbtn" id="fmt_align_justify" title="两端对齐">☰</button>'
        '<button type="button" class="fmtbtn" id="fmt_indent_inc" title="增加缩进">→</button>'
        '<button type="button" class="fmtbtn" id="fmt_indent_dec" title="减少缩进">←</button>'
        '<select class="fmtselect" id="fmt_linespace" title="行距">'
        '<option value="">行距</option>'
        '<option value="1">单倍</option><option value="1.5">1.5倍</option>'
        '<option value="2">2倍</option><option value="28pt">固定28pt</option>'
        '</select>'
        '</div>'
        '</div></div>'
        '<div class="fmtpeek" title="悬停展开格式工具栏"></div>'
    )
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<style>' + scss + '</style></head><body>'
        + sfmtbar
        + '<div class="docworkspace"><div class="docpage docpreview">' + sbody + '</div></div>'
        '<div id="docstatus" class="docstatus"></div>'
        '<script>' + sjs + '</script></body></html>'
    )


def InvalidateEditorCache(sdocid=None):
    global _oEditorHtmlCache
    if sdocid is None:
        _oEditorHtmlCache = {}
        return
    vkeys = [k for k in _oEditorHtmlCache if k.startswith(sdocid + ":")]
    for skey in vkeys:
        _oEditorHtmlCache.pop(skey, None)


def GetEditorHtml(sdocid, stheme="girly"):
    spath = os.path.join(DocDir(sdocid), "current.docx")
    if not os.path.isfile(spath):
        raise ValueError("文档不存在")
    if stheme not in _EDITOR_THEME_CSS:
        stheme = "girly"
    scache_key = _EditorCacheKey(sdocid, stheme)
    if scache_key and scache_key in _oEditorHtmlCache:
        return _oEditorHtmlCache[scache_key]
    shtml = RenderEditorHtml(sdocid, stheme)
    if scache_key:
        _TouchEditorCache(scache_key, shtml)
    return shtml

