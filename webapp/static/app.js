document.addEventListener('DOMContentLoaded', () => {
    // DOM 요소
    const chatMessages = document.getElementById('chat-messages');
    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const btnSend = document.getElementById('btn-send');
    const btnNewChat = document.getElementById('btn-new-chat');
    const themeToggle = document.getElementById('theme-toggle');
    const newsContent = document.getElementById('news-content');
    const newsLoading = document.getElementById('news-loading');
    const suggestionChips = document.querySelectorAll('.chip');

    // 상태 관리
    let isWaitingForResponse = false;
    let sessionId = 'session_' + Math.random().toString(36).substr(2, 9);

    // marked.js 옵션 설정 (마크다운 렌더링)
    marked.setOptions({
        breaks: true,
        gfm: true
    });

    // 1. 테마 토글
    themeToggle.addEventListener('click', () => {
        const body = document.body;
        const icon = themeToggle.querySelector('i');
        const span = themeToggle.querySelector('span');

        if (body.classList.contains('dark-theme')) {
            body.classList.replace('dark-theme', 'light-theme');
            icon.classList.replace('fa-sun', 'fa-moon');
            span.textContent = '다크 모드';
            localStorage.setItem('theme', 'light');
        } else {
            body.classList.replace('light-theme', 'dark-theme');
            icon.classList.replace('fa-moon', 'fa-sun');
            span.textContent = '라이트 모드';
            localStorage.setItem('theme', 'dark');
        }
    });

    // 저장된 테마 불러오기
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'light') {
        document.body.classList.replace('dark-theme', 'light-theme');
        themeToggle.querySelector('i').classList.replace('fa-sun', 'fa-moon');
        themeToggle.querySelector('span').textContent = '다크 모드';
    }

    // 2. 오늘의 뉴스 인사이트 로드
    async function loadNewsInsight() {
        newsContent.classList.add('hidden');
        newsLoading.classList.remove('hidden');

        try {
            const response = await fetch('/api/news-insight');
            const data = await response.json();

            if (data.error) {
                newsContent.innerHTML = `<p class="placeholder-text text-error">뉴스를 불러오는 중 오류가 발생했습니다.<br>(${data.error})</p>`;
            } else {
                newsContent.innerHTML = marked.parse(data.insights);
            }
        } catch (error) {
            newsContent.innerHTML = `<p class="placeholder-text text-error">네트워크 오류가 발생했습니다.</p>`;
        } finally {
            newsLoading.classList.add('hidden');
            newsContent.classList.remove('hidden');
        }
    }

    // 초기 뉴스 로드
    loadNewsInsight();

    // 3. 채팅 UI 조작

    // 자동 크기 조절 텍스트 영역
    chatInput.addEventListener('input', function () {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
        btnSend.disabled = this.value.trim() === '';
    });

    // 엔터키 전송 (Shift+Enter는 줄바꿈)
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (!btnSend.disabled && !isWaitingForResponse) {
                chatForm.dispatchEvent(new Event('submit'));
            }
        }
    });

    // 하단 스크롤
    function scrollToBottom() {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    // 메시지 UI 추가
    function appendMessage(role, content) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${role === 'user' ? 'user-message' : 'system-message'}`;

        const iconClass = role === 'user' ? 'fa-user' : 'fa-robot';
        const parsedContent = role === 'user' ? content.replace(/\n/g, '<br>') : marked.parse(content);

        messageDiv.innerHTML = `
            <div class="message-avatar"><i class="fa-solid ${iconClass}"></i></div>
            <div class="message-content">${parsedContent}</div>
        `;

        chatMessages.appendChild(messageDiv);
        scrollToBottom();
    }

    // 로딩 인디케이터
    const loadingHtml = `
        <div class="message system-message" id="typing-indicator">
            <div class="message-avatar"><i class="fa-solid fa-robot"></i></div>
            <div class="message-content">
                <div class="typing-indicator">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            </div>
        </div>
    `;

    function showLoading() {
        chatMessages.insertAdjacentHTML('beforeend', loadingHtml);
        scrollToBottom();
    }

    function hideLoading() {
        const indicator = document.getElementById('typing-indicator');
        if (indicator) indicator.remove();
    }

    // 추천 질문 클릭
    suggestionChips.forEach(chip => {
        chip.addEventListener('click', () => {
            chatInput.value = chip.textContent;
            chatInput.style.height = 'auto';
            btnSend.disabled = false;
        });
    });

    // 새 대화 시작
    btnNewChat.addEventListener('click', () => {
        sessionId = 'session_' + Math.random().toString(36).substr(2, 9);
        chatMessages.innerHTML = `
            <div class="message system-message">
                <div class="message-avatar"><i class="fa-solid fa-robot"></i></div>
                <div class="message-content">
                    <p>새로운 대화를 시작합니다. 무엇을 도와드릴까요?</p>
                </div>
            </div>
        `;
    });

    // 4. API 서버 통신 (채팅 전송)
    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const message = chatInput.value.trim();
        if (!message) return;

        // UI 업데이트
        appendMessage('user', message);
        chatInput.value = '';
        chatInput.style.height = 'auto';
        btnSend.disabled = true;
        isWaitingForResponse = true;
        showLoading();

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    question: message,
                    thread_id: sessionId
                })
            });

            const data = await response.json();
            hideLoading();

            if (data.error) {
                appendMessage('system', `⚠️ **오류 발생:**\n${data.error}`);
            } else {
                appendMessage('system', data.answer);
            }
        } catch (error) {
            hideLoading();
            appendMessage('system', `⚠️ **네트워크 오류:** 서버와 연결할 수 없습니다.`);
        } finally {
            isWaitingForResponse = false;
        }
    });
});
