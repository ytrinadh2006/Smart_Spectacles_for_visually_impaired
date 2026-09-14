# Instructions for Person 1 (Repo Creator / Lead)

You are initializing the central repository for the team so your 4 teammates can fork it and send merge requests.

### Steps:
1. Go to https://github.com/new and create a new repository called `smart-specs`.
   - Leave "Add a README", ".gitignore", and "license" UNCHECKED.
2. In your local terminal, navigate inside this folder:
   ```bash
   cd 01_repo_creator_base
   git init
   git add .
   git commit -m "Initial commit: Base project skeleton, architecture, and docs"
   git branch -M main
   git remote add origin https://github.com/<YOUR_USERNAME>/smart-specs.git
   git push -u origin main
   ```
3. Share your repo link `https://github.com/<YOUR_USERNAME>/smart-specs` with your 4 teammates!
4. When teammates submit Pull Requests, you review and click **Merge pull request**!
