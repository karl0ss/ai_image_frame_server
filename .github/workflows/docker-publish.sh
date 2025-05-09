name: Build and Publish Docker Image

on:
  push:
    branches: [main]
    tags: ['*']  # triggers on any tag push
  workflow_dispatch:

jobs:
  build-and-push:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to Docker Registry
        run: echo "${{ secrets.PASSWORD }}" | docker login ${{ secrets.REGISTRY }} -u "${{ secrets.USERNAME }}" --password-stdin

      - name: Build and Push Docker Images
        run: |
          IMAGE_NAME="ai-frame-image-server"
          REGISTRY="${{ secrets.REGISTRY }}"
          USERNAME="${{ secrets.USERNAME }}"
          IMAGE_LATEST="$REGISTRY/$USERNAME/$IMAGE_NAME:latest"

          # Always build and tag as latest
          echo "🔧 Building $IMAGE_LATEST"
          docker build -t $IMAGE_LATEST .

          echo "📤 Pushing $IMAGE_LATEST"
          docker push $IMAGE_LATEST

          # If this is a tag push, tag the image accordingly
          if [[ "${GITHUB_REF}" == refs/tags/* ]]; then
            GIT_TAG="${GITHUB_REF#refs/tags/}"
            IMAGE_TAGGED="$REGISTRY/$USERNAME/$IMAGE_NAME:$GIT_TAG"

            echo "🏷️ Also tagging as $IMAGE_TAGGED"
            docker tag $IMAGE_LATEST $IMAGE_TAGGED

            echo "📤 Pushing $IMAGE_TAGGED"
            docker push $IMAGE_TAGGED
          fi
