# PLAN.md - Project Overview & Development Roadmap

This document serves as the master blueprint for the project. It outlines the core architecture, functional requirements, and execution steps to guide AI assistants and developers throughout the development lifecycle.

---

## 1. Project Description

### Overview
This project is an expense management and splitting application designed to help roommates track, calculate, and reconcile shared household expenses easily. The core problem it solves is the manual friction of pulling transactions from bank statements (like Chase exports) and manually calculating fair splits.

### Primary Purpose
- Import expense data via standard file exports (e.g., CSV/JSON bank records).
- Provide a clear interface for categorizing, splitting, and filtering transactions.
- Calculate exact balances owed between household members.
- Export clean summaries or generate settlement links (e.g., Venmo/Zelle text summaries).

---

## 2. Core Features & Functional Scope

### Phase 1: MVP (Minimum Viable Product)
- **Data Ingestion:** Upload and parse bank CSV/statement exports (Chase schema primary).
- **Expense Categorization:** Tag items as "Shared" or "Personal" and assign dynamic split ratios (e.g., 50/50, 60/40, fixed amounts).
- **Balance Calculator:** Automatically aggregate shared totals and output individual net balances.
- **Export & Summary:** Generate a clean line-item summary and final balance text to copy/paste.

### Phase 2: Enhanced Features
- **Recurring Expense Engine:** Auto-detect recurring monthly bills (rent, utilities, internet).
- **Multi-User Profiles:** Support for 2+ housemates with custom split defaults.
- **Visual Analytics:** Summary charts showing monthly household expenditure breakdowns by category.

---

## 3. Tech Stack & Architecture

- **Frontend Framework:** React (Next.js) or modern HTML/CSS/JS single-page application.
- **Styling:** Tailwind CSS or UI component library for responsive layout.
- **Data Parsing:** CSV parser library (e.g., PapaParse) running client-side.
- **State Management:** Local React state / Context API (or persistent browser storage via `localStorage`).

---

## 4. Immediate Development Roadmap

1. **Setup & Boilerplate:**
   - Initialize project repository structure.
   - Configure build tools, linters, and baseline UI layout.

2. **Parser Module:**
   - Build a robust CSV parser tuned to standard Chase credit/checking statement headers.
   - Create data normalizers for transaction date, description, and amount.

3. **Split Calculation Logic:**
   - Implement state management for transaction lists.
   - Write unit functions for splitting algorithms ($50/50$, customized ratio, excluded items).

4. **UI & Reconciliation View:**
   - Create a clean transaction list view with toggleable split flags.
   - Design a dynamic dashboard card displaying "Who owes whom how much".

---

## 5. Instructions for AI Assistants (e.g., Claude)

- **Context Awareness:** Refer to this document for overall architecture, user intent, and naming conventions before generating new code.
- **Code Style:** Prefer modular, functional code with clear type definitions (TypeScript preferred where applicable) and minimal external dependencies.
- **Incremental Builds:** When prompted to implement a feature, refer to the numbered steps in Section 4 and build one isolated module at a time.
