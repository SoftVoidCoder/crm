## Styles structure

style.css stays as the public entrypoint for legacy pages and deploy checks.

Files are split into two main groups:

- legacy/
- 	ailwind/

legacy/ keeps older global and module-specific layers that still power the existing CRM screens.

	ailwind/ is the structured design layer for newer UX work:

- oundation.css for shared CRM shell polish and readable defaults
- 	okens.css for design tokens
- components.css for reusable UI primitives
- enterprise.css for workspace-level layouts and final overrides
- utilities.css for 	w-* compatibility classes used in templates