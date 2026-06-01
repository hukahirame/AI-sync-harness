// ==UserScript==
// @name         AI Chat Auto-Saver (Project chats only)
// @namespace    local.ai-chat-saver
// @version      0.3.0
// @description  プロジェクト内のチャットだけをローカルサーバーに自動保存(Claude: API横取り方式)
// @author       you
// @match        https://claude.ai/*
// @match        https://chatgpt.com/*
// @match        https://chat.openai.com/*
// @grant        GM_xmlhttpRequest
// @grant        unsafeWindow
// @connect      localhost
// @connect      127.0.0.1
// @run-at       document-start
// ==/UserScript==

(function () {
    'use strict';

    const ENDPOINT = 'http://127.0.0.1:9999/save';
    const DEBOUNCE_MS = 5000;
    const MIN_MESSAGES = 2;
    const LOG_PREFIX = '[AI-Saver]';

    let lastHash = null;

    function hashString(s) {
        let h = 0;
        for (let i = 0; i < s.length; i++) {
            h = ((h << 5) - h) + s.charCodeAt(i);
            h |= 0;
        }
        return h.toString(16);
    }

    function saveToServer(payload) {
        const json = JSON.stringify(payload);
        const h = hashString(json);
        if (h === lastHash) return;

        GM_xmlhttpRequest({
            method: 'POST',
            url: ENDPOINT,
            headers: { 'Content-Type': 'application/json' },
            data: json,
            timeout: 5000,
            onload: (res) => {
                if (res.status === 200) {
                    lastHash = h;
                    console.log(LOG_PREFIX, '✅ 保存しました:', payload.title, `(${payload.messages.length} msgs)`);
                } else {
                    console.warn(LOG_PREFIX, '❌ サーバーエラー:', res.status, res.responseText);
                }
            },
            onerror: () => console.warn(LOG_PREFIX, '❌ ローカルサーバーに接続できません。'),
            ontimeout: () => console.warn(LOG_PREFIX, '❌ タイムアウト'),
        });
    }

    // ============================================================
    //   Claude: API横取り方式
    // ============================================================
    if (location.hostname.includes('claude.ai')) {

        let lastConvFetchUrl = null;
        let refetchTimer = null;

        function handleClaudeConversation(data) {
            if (!data || !Array.isArray(data.chat_messages)) return;
            if (!data.project || !data.project.uuid) {
                // プロジェクト外: スキップ
                return;
            }

            const messages = data.chat_messages.map(msg => {
                // content 配列から text タイプだけを連結
                const textParts = (msg.content || [])
                    .filter(c => c.type === 'text')
                    .map(c => (c.text || '').trim())
                    .filter(t => t);
                return {
                    role: msg.sender === 'human' ? 'user' : 'assistant',
                    text: textParts.join('\n\n'),
                    timestamp: msg.created_at,
                };
            }).filter(m => m.text);

            if (messages.length < MIN_MESSAGES) {
                console.log(LOG_PREFIX, 'メッセージ数が少ないのでスキップ:', messages.length);
                return;
            }

            saveToServer({
                ai: 'claude',
                project: data.project.name,
                title: data.name || 'Untitled',
                url: `https://claude.ai/chat/${data.uuid}`,
                timestamp: data.updated_at || new Date().toISOString(),
                messages: messages,
            });
        }

        // fetch をフックして、会話APIのレスポンスを横取り
        const origFetch = unsafeWindow.fetch.bind(unsafeWindow);
        unsafeWindow.fetch = async function (...args) {
            const response = await origFetch.apply(this, args);
            try {
                const url = typeof args[0] === 'string' ? args[0] : args[0]?.url;
                if (url && /\/chat_conversations\/[a-f0-9-]{36}/.test(url) && response.ok) {
                    lastConvFetchUrl = url;
                    response.clone().json().then(data => {
                        if (data && Array.isArray(data.chat_messages)) {
                            handleClaudeConversation(data);
                        }
                    }).catch(() => {});
                }
            } catch (e) {}
            return response;
        };

        // DOM 変化を見て、5秒静止後に会話APIを再取得
        // (新メッセージが流れ込んでも、再取得すれば最新が拾える)
        function scheduleRefetch() {
            clearTimeout(refetchTimer);
            refetchTimer = setTimeout(() => {
                if (lastConvFetchUrl) {
                    origFetch(lastConvFetchUrl, { credentials: 'include' }).catch(() => {});
                    // ↑ レスポンスは上のフックが捕まえる
                }
            }, DEBOUNCE_MS);
        }

        function startObserver() {
            if (!document.body) { setTimeout(startObserver, 100); return; }
            new MutationObserver(scheduleRefetch).observe(document.body, {
                childList: true, subtree: true, characterData: true,
            });
            console.log(LOG_PREFIX, 'Claude API hook installed');
        }
        startObserver();

        return; // ここで終わり
    }

    // ============================================================
    //   ChatGPT: 従来通り DOM 監視方式(まだ作り変えてない)
    // ============================================================
    if (location.hostname.includes('chatgpt.com') || location.hostname.includes('chat.openai.com')) {
        let saveTimer = null;

        function getMessages() {
            const out = [];
            document.querySelectorAll('[data-message-author-role]').forEach(el => {
                const role = el.getAttribute('data-message-author-role');
                const text = el.innerText.trim();
                if (text) out.push({ role, text });
            });
            return out;
        }
        const isProjectChat = () => /\/g\/g-p-/.test(location.pathname);
        const getProjectName = () => (location.pathname.match(/\/g\/(g-p-[^/]+)/) || [])[1] || null;
        const getTitle = () => document.title.replace(/\s*[-|]\s*ChatGPT.*$/i, '').trim() || 'Untitled';

        function snapshotAndSave() {
            if (!isProjectChat()) return;
            const messages = getMessages();
            if (messages.length < MIN_MESSAGES) return;
            saveToServer({
                ai: 'chatgpt',
                project: getProjectName(),
                title: getTitle(),
                url: location.href,
                timestamp: new Date().toISOString(),
                messages,
            });
        }

        function scheduleSave() {
            clearTimeout(saveTimer);
            saveTimer = setTimeout(snapshotAndSave, DEBOUNCE_MS);
        }
        function startObserver() {
            if (!document.body) { setTimeout(startObserver, 100); return; }
            new MutationObserver(scheduleSave).observe(document.body, {
                childList: true, subtree: true, characterData: true,
            });
            console.log(LOG_PREFIX, 'ChatGPT DOM監視を開始');
        }
        startObserver();

        window.addEventListener('beforeunload', () => {
            clearTimeout(saveTimer);
            snapshotAndSave();
        });
    }
})();