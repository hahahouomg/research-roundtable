"use strict";

function stageHistory(record) {
  const groups = new Map();
  for (const call of record.calls) {
    if (!groups.has(call.stage)) groups.set(call.stage, []);
    groups.get(call.stage).push(call);
  }
  return [...groups].map(([name, calls]) => ({name, calls}));
}
// Some CLI versions print the same ballot twice. Keep the original reply available in the reader.
function ballotData(raw) {
  if(typeof raw!=="string")return null;
  let value;
  try { value=JSON.parse(raw); }
  catch {
    for(const boundary of raw.matchAll(/}\s*(?=\{)/g)){
      try {
        const end=boundary.index+1, first=JSON.parse(raw.slice(0,end)), second=JSON.parse(raw.slice(end));
        const keys=Object.keys(first);
        if(keys.length===Object.keys(second).length && keys.every(k=>Object.hasOwn(second,k) && first[k]===second[k])){
          value=first;
          break;
        }
      } catch { /* A brace inside a quoted reason is not a record boundary. */ }
    }
  }
  return value && ["accept","object"].includes(value.vote) && typeof value.reason==="string" && value.reason.trim() ? value : null;
}
function voteOf(call) {
  return call.ended && !call.error ? ballotData(call.reply)?.vote || null : null;
}

let inspectedSession=null, inspectedPhase=null;

function selectVisualPhase(value){
  const s=data.selected;
  if(!s)return;
  const stage=stageHistory(s)[Number(value)];
  if(value!==null && !stage)return;
  inspectedPhase=value===null || (ongoing(s.state) && stage.name===s.calls.at(-1)?.stage) ? null : stage.name;
  const root=$("discussionVisual"), trigger=document.activeElement;
  if(!root)return;
  const fromVisual=root.contains(trigger), visual=visualModel(s,sessionDocuments(s));
  const template=document.createElement("template");
  template.innerHTML=window.createDiscussionVisual(visual);
  patchChildren(root,template.content);
  window.syncDiscussionVisual?.(root,visual);
  if(fromVisual && !trigger.isConnected){
    const dest=value!==null && root?.querySelector('[data-visual-phase="'+Number(value)+'"]');
    (dest || root)?.focus({preventScroll:true});
  }
}
function focusToolRequest(id){
  const card=document.querySelector('.permission[data-key="permission-'+Number(id)+'"]');
  if(!card)return;
  card.focus({preventScroll:true});
  card.scrollIntoView({block:"center",behavior:motionAllowed.matches?"smooth":"auto"});
}

function visualKind(name){
  if(name.startsWith("表决"))return "ballot";
  if(name.startsWith("候选方案"))return "draft";
  return ({"独立提案":"proposal","交叉评议":"review","最终方案撰写":"document","图文 PDF 排版":"document","讨论总结":"document","实施":"execution","集成复核":"execution"})[name] || "other";
}
function visualModel(s,docs){
  const ids=[...new Set([...(s.seat_names||[]),...s.calls.map(c=>c.agent)])].filter(a=>Object.hasOwn(labels,a));
  if(ids.length<2)return null;
  if(inspectedSession!==s.id){inspectedSession=s.id;inspectedPhase=null;}
  const requests=(s.permissions||[]).map(r=>{
    const d=r.details||{};
    return {id:r.id,agent:r.agent,stage:r.stage,title:String((d.rawInput||d.args)?.toolSummary || d.title || d.kind || t("工具请求"))};
  });
  const running=ongoing(s.state);
  let previousVotes=[];
  const phases=stageHistory(s).map(stage=>{
    const kind=visualKind(stage.name);
    const seats=ids.map(id=>{
      const c=stage.calls.filter(c=>c.agent===id).at(-1);
      if(!c && kind==="ballot" && stage.name.includes("同稿补票")){
        const prior=previousVotes.find(b=>b.id===id && b.vote);
        if(prior)return {...prior,carried:true};
      }
      const req=c && !c.ended && requests.find(r=>r.stage===stage.name && r.agent===id);
      const vote=kind==="ballot" && c && c.ended && !c.error ? ballotData(c.reply) : null;
      const state=!c ? "absent" : req ? "permission" : c.error ? "error" : !c.ended ?
        (running ? (c.reply?"writing":"pending") : "unfinished") : kind==="ballot" ? (vote?.vote||"invalid") : "done";
      return {id,name:labels[id],state,callId:c?.id??null,excerpt:vote ? "" : (c && (c.error||shortCall(c)) || "").slice(0,320),
        reason:vote?.reason||"",vote:vote?.vote||null,carried:false,requestId:req?.id??null,requestTitle:req?.title||""};
    });
    if(kind==="ballot")previousVotes=seats;
    return {name:stage.name,title:displayStage(stage.name),kind,seats};
  });
  const latest=phases.findIndex(p=>p.name===s.calls.at(-1)?.stage);
  const pinned=phases.findIndex(p=>p.name===inspectedPhase);
  const lastVote=phases.findLastIndex(p=>p.kind==="ballot");
  const index=pinned>=0 ? pinned : !running && lastVote>=0 ? lastVote : latest;
  return {id:s.id,language:uiLanguage(),topic:s.topic,status:s.state,running,stopping:Boolean(s.stop_requested),
    following:running && pinned<0,index,latest,agents:ids.map(id=>({id,name:labels[id]})),phases,requests,
    documents:docs.map(d=>({id:d.key,name:d.name}))};
}

function voteHistory(record){
  const rounds=stageHistory(record).filter(stage=>stage.name.startsWith("表决"));
  if(!rounds.length)return "";
  const agents=[...new Set(rounds.flatMap(stage=>stage.calls.map(c=>c.agent)))];
  const rows=rounds.map(stage=>{
    const votes=agents.map(agent=>{
      const call=stage.calls.filter(c=>c.agent===agent).at(-1);
      if(!call)return "<td>—</td>";
      const vote=voteOf(call);
      const label=vote==="accept"?"赞成":vote==="object"?"有异议":call.error?"已中断":call.ended?"无有效票":"等待回复…";
      return `<td><button class="ballot-mark ${vote||""}" data-read="call-${Number(call.id)}" aria-label="${esc(labels[agent]+" · "+displayStage(stage.name)+" · "+t(label))}">${vote==="accept"?"✓ ":vote==="object"?"− ":""}${t(label)}</button></td>`;
    }).join("");
    return "<tr><th scope='row'>"+esc(displayStage(stage.name))+"</th>"+votes+"</tr>";
  }).join("");
  return `<div class="ballot-history"><table><caption>${t("逐版表决")}</caption><thead><tr><th scope="col">${t("阶段")}</th>${agents.map(a=>'<th scope="col">'+esc(labels[a]||a)+'</th>').join("")}</tr></thead><tbody>${rows}</tbody></table></div>`;
}
function sessionDocuments(record) {
  const docs = [];
  const add = (key, name, text) => { if(text) docs.push({key,name:t(name),text}); };
  add("final","最终方案 · Gemini 执笔",finalDraft(record));
  add("summary","讨论总结",closingDraft(record));
  const approved = ["consensus","implementing","returned","inspect"].includes(record.state) || finalDraft(record) || record.workspace;
  add("plan",approved?"全体表决通过的原稿及分工":"候选方案",record.plan);
  const reports = record.calls.filter(c=>["实施","集成复核"].includes(c.stage) && c.reply);
  if(reports.length) docs.unshift({key:"reports",name:t("实施报告"),text:reports.map(c=>
    "## "+labels[c.agent]+" · "+displayStage(c.stage)+"\n\n"+readCall(c)).join("\n\n")});
  const reply = record.calls.filter(c=>c.stage==="单聊" && c.reply).at(-1);
  if(reply) add("reply","回复",reply.reply);
  return docs;
}
function readCall(call) {
  const text = call.reply || "";
  if(call.error) return [call.error, text].filter(Boolean).join("\n\n");
  if(call.stage.startsWith("表决")) return ballot(text);
  try {
    const structured=JSON.parse(text);
    if(typeof structured.report==="string")return structured.report;
    if(typeof structured.plan==="string")return structured.plan + (Array.isArray(structured.tasks)?
      "\n\n## "+t("任务分工")+"\n"+structured.tasks.map(task=>"\n- "+[task.owner,task.task,task.acceptance].filter(Boolean).join(" · ")).join(""):"");
  } catch {}
  return text || t("等待回复…");
}
function shortCall(call){
  const raw=call.reply || "";
  let text=raw;
  try{
    const obj=JSON.parse(raw);
    text=[obj.reason,obj.summary,obj.plan,obj.report,obj.items?.[0]?.claim].find(v=>typeof v==="string") || "";
  }catch{}
  return text.split("\n").map(s=>s.trim()).find(s=>s && !/^[#<{`|]/.test(s))?.replace(/^>\s*|\*\*/g,"") || "";
}
function documentCard(doc){
  const lines=doc.text.split("\n").map(s=>s.trim()).filter(Boolean);
  const title=lines[0]?.match(/^#\s+(.+)$/)?.[1];
  const paragraph=lines.find(s=>!s.startsWith("#") && !/^[-|`]/.test(s)) || lines[0] || "";
  const excerpt=paragraph.replace(/^>\s*/, "").replace(/\*\*|`/g,"");
  let fenced=false;
  const chapters=[];
  for(const line of lines){
    if(line.startsWith("```")){fenced=!fenced;continue;}
    const heading=!fenced && line.match(/^##\s+(.+)$/);
    if(heading && !chapters.includes(heading[1]))chapters.push(heading[1]);
    if(chapters.length===3)break;
  }
  const contents=chapters.length>1 ? `<nav class="cover-chapters" aria-label="${t("章节直达")}"><h3>${t("章节直达")}</h3>${chapters.map(name=>
    `<button data-read="${doc.key}" data-heading="${esc(name)}"><span>${inline(name)}</span>${icon("chevron")}</button>`).join("")}</nav>` : "";
  return `<article class="document-cover" data-key="result"><div class="cover-copy">${title?'<div class="doc-byline">'+icon("note")+esc(doc.name)+'</div>':""}
    <h2>${esc(title || doc.name)}</h2><p>${esc(excerpt.slice(0,145))}${excerpt.length>145?"…":""}</p>
    <button class="read-document" data-read="${doc.key}">${t("阅读全文")} ${icon("arrow")}</button></div>${contents}</article>`;
}
function docRow(doc){
  return `<button class="doc-row" data-key="doc-${doc.key}" data-read="${doc.key}"><span>${esc(doc.name)}</span></button>`;
}

let readerSession, readerTrigger, readerCall, returnScroll, readerSections=[];
function openReader(key, trigger) {
  const record=data.selected;
  if(!record)return;
  const dialog=$("reader");
  const docs=sessionDocuments(record);
  if(!dialog.open)readerCall=null;
  if(key.startsWith("call-"))readerCall=record.calls.find(c=>"call-"+c.id===key);
  if(readerCall){
    const callKey="call-"+readerCall.id, text=readCall(readerCall);
    docs.unshift({key:callKey,name:labels[readerCall.agent]+" · "+displayStage(readerCall.stage),text});
    if(readerCall.reply && readerCall.reply!==text)docs.push({key:"raw",name:t("原始发言"),text:readerCall.reply});
  }
  const doc=docs.find(d=>d.key===key);
  if(!doc)return;
  const opening=!dialog.open;
  if(opening){
    readerSession=record.id;readerTrigger=trigger;returnScroll=$("stage").scrollTop;
  }
  $("readerTitle").textContent=doc.name;
  const menu=$("readerDocs");
  menu.innerHTML='<option value="" disabled>'+t("切换文稿")+'</option>'+
    docs.map(d=>`<option value="${esc(d.key)}">${d.key===key?"✓ ":""}${esc(d.name)}</option>`).join("");
  menu.value="";
  menu.hidden=docs.length<2;
  const body=$("readerText");
  body.innerHTML=prose(doc.text);
  readerSections=[...body.querySelectorAll("h4,h5")];
  const outline=$("readerOutline");
  outline.innerHTML=readerSections.map((h,i)=>{
    h.id="reading-heading-"+i;
    return `<option value="${i}">${esc(h.textContent)}</option>`;
  }).join("");
  $("readerOutlineLabel").hidden=!readerSections.length;
  const nav=$("readerNav");
  nav.hidden=!readerSections.length;
  nav.innerHTML=readerSections.map((h,i)=>`<button data-chapter="${i}" class="${h.tagName==="H5"?"nested":""}">${esc(h.textContent)}</button>`).join("");
  if(!dialog.open)dialog.showModal();
  $("readerScroll").scrollTop=0;
  updateReading();
  if(opening)$("readerClose").focus({preventScroll:true});
  const heading=trigger?.dataset.heading;
  if(heading && trigger?.dataset.read===key){
    const tmp=document.createElement("span");
    tmp.innerHTML=inline(heading);
    const index=readerSections.findIndex(h=>h.textContent===tmp.textContent);
    if(index>=0)jumpChapter(index);
  }
  enter(body);
}
function updateReading(){
  const box=$("readerScroll"), offset=box.getBoundingClientRect().top+28;
  const range=box.scrollHeight-box.clientHeight;
  $("readerProgress").value=range?Math.min(100,100*box.scrollTop/range):100;
  if(!readerSections.length)return;
  let index=readerSections.findIndex(h=>h.getBoundingClientRect().top>offset)-1;
  if(index===-2)index=readerSections.length-1;
  index=Math.max(0,index);
  $("readerOutline").value=String(index);
  const nav=$("readerNav"), active=nav.children[index];
  if(active && !active.hasAttribute("aria-current")){
    nav.querySelector("[aria-current]")?.removeAttribute("aria-current");
    active.setAttribute("aria-current","location");
    if(active.offsetTop<nav.scrollTop || active.offsetTop+active.offsetHeight>nav.scrollTop+nav.clientHeight){
      nav.scrollTop=active.offsetTop-nav.clientHeight/3;
    }
  }
}
function jumpChapter(index) {
  readerSections[index]?.scrollIntoView({block:"start",behavior:"instant"});
  updateReading();
}
