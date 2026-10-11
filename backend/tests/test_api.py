def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/auth/bootstrap").json()["needs_setup"] is True


def test_auth_registration_and_login(client, auth):
    assert client.get("/api/auth/me", headers=auth).json()["role"] == "admin"
    assert client.post("/api/auth/register", json={"name": "Other User", "email": "other@example.com", "password": "another-password"}).status_code == 403
    assert client.post("/api/auth/login", json={"email": "admin@example.com", "password": "wrong-password"}).status_code == 401
    assert client.get("/api/tickets").status_code == 401


def test_knowledge_tickets_and_review(client, auth):
    document = client.post("/api/documents", json={"title": "Invoice and payment policy", "content": "For incorrect invoices, customers should share their invoice number with the billing team. Duplicate charges must be verified before a refund is authorized. Approved refunds take five business days."}, headers=auth)
    assert document.status_code == 201, document.text
    ticket = client.post("/api/tickets", json={"subject": "Duplicate invoice charge", "message": "My card has been charged twice. Please send a refund right away.", "customer_name": "Alex Customer", "customer_email": "alex@example.com"}, headers=auth)
    assert ticket.status_code == 201, ticket.text
    data = ticket.json()
    assert data["status"] == "pending_review"
    assert data["draft_response"]
    assert len(data["citations"]) > 0
    assert client.patch(f"/api/tickets/{data['id']}/status", json={"status": "resolved"}, headers=auth).status_code == 409
    approved = client.post(f"/api/tickets/{data['id']}/approve", json={"response": "Hello Alex, please send your invoice ID so we can investigate."}, headers=auth)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    resolved = client.patch(f"/api/tickets/{data['id']}/status", json={"status": "resolved"}, headers=auth)
    assert resolved.status_code == 200
    assert client.post(f"/api/tickets/{data['id']}/analyze", headers=auth).status_code == 409
    stats = client.get("/api/analytics", headers=auth).json()
    assert stats["resolved"] == 1
    assert stats["documents"] == 1
    assert len(client.get("/api/audit", headers=auth).json()) >= 3


def test_reject_document_upload_and_seed_guard(client, auth):
    doc = client.post("/api/documents/upload", files={"file": ("guide.txt", b"This support guide explains how customers may find account and invoice information within the settings section.")}, headers=auth)
    assert doc.status_code == 201, doc.text
    assert client.post("/api/documents/upload", files={"file": ("bad.exe", b"hello")}, headers=auth).status_code == 415
    assert client.post("/api/demo/seed", headers=auth).status_code == 409
    issue = client.post("/api/tickets", json={"subject": "Need account access", "message": "I cannot reset my account password with the link I received", "customer_name": "Taylor"}, headers=auth).json()
    assert client.post(f"/api/tickets/{issue['id']}/reject", headers=auth).json()["status"] == "open"
    assert client.post(f"/api/tickets/{issue['id']}/approve", json={"response": "approved"}, headers=auth).status_code == 409
    assert client.delete(f"/api/documents/{doc.json()['id']}", headers=auth).status_code == 204


def test_classifier_report(client, auth):
    result = client.get("/api/ml/evaluation", headers=auth)
    assert result.status_code == 200
    assert result.json()["test_samples"] == 16
    assert "accuracy" in result.json()


def test_admin_can_create_agent_but_agent_cannot_manage_users(client, auth):
    member = client.post('/api/admin/users', headers=auth, json={'name':'New Agent','email':'agent@example.com','password':'agent-password-123'})
    assert member.status_code == 201, member.text
    assert member.json()['role'] == 'agent'
    sign_in = client.post('/api/auth/login', json={'email':'agent@example.com','password':'agent-password-123'})
    agent_headers = {'Authorization': f"Bearer {sign_in.json()['token']}"}
    assert client.get('/api/admin/users', headers=agent_headers).status_code == 403
    assert client.get('/api/analytics', headers=agent_headers).status_code == 200
    assert client.post('/api/demo/seed', headers=agent_headers).status_code == 403


def test_demo_content_is_sequential_and_requires_empty_database(client, auth):
    seed = client.post('/api/demo/seed', headers=auth)
    assert seed.status_code == 200, seed.text
    assert seed.json() == {'documents':6, 'tickets':7}
    stats = client.get('/api/analytics', headers=auth).json()
    assert stats['pending'] == 7 and stats['documents'] == 6
    assert client.post('/api/demo/seed', headers=auth).status_code == 409
