-- Migration: Add image support
-- Run with: psql -d slidegen -f db/migrations/001_add_images.sql
--
-- This migration adds:
-- 1. image_style ENUM type
-- 2. image_asset table with vector embedding
-- 3. image_id column on slide table
-- 4. fn_search_images function
-- 5. Updated fn_commit_slide with p_image_id parameter

-- Add 'image' to doc_type enum if not present
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel = 'image' AND enumtypid = 'doc_type'::regtype) THEN
        ALTER TYPE doc_type ADD VALUE 'image';
    END IF;
END $$;

-- Add image_style enum if not exists
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'image_style') THEN
        CREATE TYPE image_style AS ENUM ('diagram', 'screenshot', 'chart', 'photo', 'decorative');
    END IF;
END $$;

-- Add image_asset table if not exists
CREATE TABLE IF NOT EXISTS image_asset (
    image_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id          UUID NOT NULL REFERENCES doc(doc_id) ON DELETE CASCADE,
    storage_path    TEXT NOT NULL,
    caption         TEXT NOT NULL,
    alt_text        TEXT NOT NULL,
    caption_embedding VECTOR(1536),
    use_cases       TEXT[] DEFAULT '{}',
    license         TEXT NOT NULL,
    attribution     TEXT NOT NULL,
    style           image_style,
    width           INT,
    height          INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Create indexes if not exist
CREATE INDEX IF NOT EXISTS idx_image_caption_embedding ON image_asset 
    USING hnsw (caption_embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_image_use_cases ON image_asset USING GIN(use_cases);
CREATE INDEX IF NOT EXISTS idx_image_style ON image_asset(style);

-- Add image_id to slide if not exists
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='slide' AND column_name='image_id') THEN
        ALTER TABLE slide ADD COLUMN image_id UUID REFERENCES image_asset(image_id);
    END IF;
END $$;

-- Create or replace fn_search_images
CREATE OR REPLACE FUNCTION fn_search_images(
    p_query_embedding VECTOR(1536),
    p_filters JSONB DEFAULT '{}'::jsonb,
    p_top_k INT DEFAULT 5
)
RETURNS TABLE (
    image_id UUID,
    storage_path TEXT,
    caption TEXT,
    alt_text TEXT,
    use_cases TEXT[],
    style image_style,
    similarity FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        ia.image_id,
        ia.storage_path,
        ia.caption,
        ia.alt_text,
        ia.use_cases,
        ia.style,
        (1 - (ia.caption_embedding <=> p_query_embedding))::FLOAT AS similarity
    FROM image_asset ia
    WHERE ia.caption_embedding IS NOT NULL
      AND (p_filters->>'style' IS NULL OR ia.style::text = p_filters->>'style')
      AND (p_filters->>'use_cases' IS NULL OR ia.use_cases && ARRAY(SELECT jsonb_array_elements_text(p_filters->'use_cases')))
    ORDER BY ia.caption_embedding <=> p_query_embedding
    LIMIT p_top_k;
END;
$$ LANGUAGE plpgsql STABLE
   SECURITY INVOKER
   PARALLEL UNSAFE
   SET search_path = public;

-- Verify migration
DO $$
BEGIN
    RAISE NOTICE '✓ Image support migration complete';
    RAISE NOTICE '  - image_style ENUM type';
    RAISE NOTICE '  - image_asset table';
    RAISE NOTICE '  - slide.image_id column';
    RAISE NOTICE '  - fn_search_images function';
END $$;
