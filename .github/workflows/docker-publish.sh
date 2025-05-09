name: Build and Publish Docker Image

on:
  push:
    branches: [main]  # or any other branch you want
  workflow_dispatch:

jobs:
  build-and-push:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to custom Docker registry
        run: echo "${{ secrets.PASSWORD }}" | docker login ${{ secrets.REGISTRY }} -u "${{ secrets.USERNAME }}" --password-stdin

      - name: Build Docker image
        run: |
          IMAGE_NAME="ai-frame-image-server"
          REGISTRY="${{ secrets.REGISTRY }}"
          USERNAME="${{ secrets.USERNAME }}"
          TAG="latest"
          FULL_IMAGE="$REGISTRY/$USERNAME/$IMAGE_NAME:$TAG"

          echo "🔧 Building image $FULL_IMAGE"
          docker build -t $FULL_IMAGE .

          echo "📤 Pushing $FULL_IMAGE"
          docker push $FULL_IMAGE
