# Customer Support AI Agent - AWS Bedrock AgentCore

## Project Overview
This project implements a highly capable Customer Support AI Agent using the AgentCore framework deployed on AWS Bedrock. The agent integrates multiple tools to assist users with e-commerce inquiries, including order tracking, refund processing, querying a knowledge base (RAG), long-term memory retrieval, a secure code interpreter for loyalty discounts, and a web browser tool.

---

## Testing Evidences and Scenarios

Below are the successful execution logs and screenshot evidences for the 6 required scenarios.

### Scenario 1: Order Tracking 
**Command:** `uv run agentcore invoke '{"prompt": "Can you track order ORD-001?", "customer_id": "CUST-123", "session_id": "final-t1"}'`
**Explanation:** The agent successfully connected to the Gateway API, retrieved the order status for ORD-001, and formatted the response clearly for the user. 
![Test 1: Tracking](evidences/Test%201%20-%20Order%20Tracking.png) 


---
### Scenario 2: Refunds Processing
**Command:** `uv run agentcore invoke '{"prompt": "I want to return my Kindle Paperwhite (ORD-002). Please initiate a refund.", "customer_id": "CUST-123", "session_id": "final-t2"}'`

**Explanation:** The agent accurately parsed the request, invoked the refund tool via the MCP client, and confirmed the successful initiation of the refund for ORD-002.

![Test 2: Refunds](evidences/Test%202%20-%20Refund%20Processing.png)
---

### Scenario 3: Knowledge Base (RAG)
**Command:** `uv run agentcore invoke '{"prompt": "What are the benefits of the Platinum loyalty tier?", "customer_id": "CUST-123", "session_id": "final-t3"}'`
**Explanation:** The agent successfully queried the AWS Bedrock Knowledge Base to retrieve the specific policy regarding the Platinum loyalty tier and presented the benefits to the user.

![Test 3: Knowledge Base](evidences/Test%203%20-%20Knowledge%20Base%20RAG.png)
---

### Scenario 4: Long-Term Memory
**Command 1:** `uv run agentcore invoke '{"prompt": "Hi, my name is Jane and I prefer consise responses. Just acknoledge this, say hello, and do NOT use any tools", "customer_id": "CUST-123", "session_id": "final-sA"}'`
**Command 2:** `uv run agentcore invoke '{"prompt": "What is my name and what is my communication preference?", "customer_id": "CUST-123", "session_id": "final-sB"}'`

**Explanation:** The `MemoryHook` correctly fetched the customer's previous preferences (e.g., concise responses and name) and injected them into the payload, allowing the model to respond according to past interactions.

![Test 4: Memory](evidences/Test%204%20-%20LongTerm%20Memory.png)
---

### Scenario 5: Loyalty Discount (Code Interpreter)
**Command:** `uv run main.py '{"prompt": "I am a Gold member with 4250 points. Calculate my discount on a $150 standard order.", "customer_id": "CUST-123", "session_id": "test-5"}'`

**Explanation:** The agent successfully ran the custom Python script within the secure AWS Sandbox environment (`code_session`). It accurately deduced points, applied tier discounts, and successfully returned the final mathematical breakdown. 

![Test 5: Code Interpreter](evidences/Test%205%20-%20Loyalty%20discount%20calculation.png)
---

### Scenario 6: Web Browser Tool
**Command:** `uv run main.py '{"prompt": "Go to https://www.udacity.com and tell me the page title.", "customer_id": "CUST-123", "session_id": "test-6"}'`

**Explanation:** To demonstrate the functional logic of the `AgentCoreBrowser` tool, the test was validated successfully in the local CLI where it extracted the correct title. Additionally, the AWS Console screenshot validates that the agent successfully initialized the cloud browser container and loaded the external website. (Note: Cloud CLI invocations were limited by sandbox IAM role permissions, but local and console tests prove the logic and integration are fully functional).

![Test 6: Browser Local CLI](evidences/Test%206%20-%20Browser%20Tool.png)

![Test 6: Browser AWS Console](evidences/Test%206%20-%20Browser%20Tool%20AWS.png)
