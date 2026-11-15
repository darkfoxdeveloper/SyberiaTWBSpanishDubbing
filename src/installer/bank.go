package main

import (
	"encoding/binary"
	"errors"
	"sort"
)

type bankChunk struct{ start, size int }

func replaceEventIDs(blob []byte, aliases map[uint32]uint32) error {
	invalid := errors.New("no se pudieron enlazar los eventos de voz")
	u32 := binary.LittleEndian.Uint32
	for start := 0; start+8 <= len(blob); {
		tag := string(blob[start : start+4])
		end := start + 8 + int(u32(blob[start+4:]))
		if end > len(blob) {
			return invalid
		}
		if tag != "HIRC" {
			start = end
			continue
		}
		if end-start < 12 {
			return invalid
		}
		count, at := u32(blob[start+8:]), start+12
		changes := make(map[int]uint32)
		seen := make(map[uint32]bool)
		for i := uint32(0); i < count; i++ {
			if end-at < 9 {
				return invalid
			}
			size, identity := int(u32(blob[at+1:])), u32(blob[at+5:])
			if size < 4 || size > end-at-5 || seen[identity] {
				return invalid
			}
			seen[identity] = true
			if next, ok := aliases[identity]; ok && blob[at] == 4 {
				changes[at+5] = next
			}
			at += 5 + size
		}
		if at != end || len(changes) != len(aliases) {
			return invalid
		}
		for offset, identity := range changes {
			if identity == 0 || seen[identity] {
				return invalid
			}
			seen[identity] = true
			binary.LittleEndian.PutUint32(blob[offset:], identity)
		}
		return nil
	}
	return invalid
}

func rebuildBank(blob []byte, edits map[uint32][]byte) ([]byte, error) {
	invalid := errors.New("el índice de audio del banco no coincide")
	labels := []string{"BKHD", "DIDX", "DATA", "HIRC"}
	layout := make([]bankChunk, len(labels))
	at := 0
	u32 := binary.LittleEndian.Uint32
	put := binary.LittleEndian.PutUint32
	for i, label := range labels {
		if len(blob)-at < 8 || string(blob[at:at+4]) != label {
			return nil, invalid
		}
		size := int(u32(blob[at+4:]))
		at += 8
		if size > len(blob)-at {
			return nil, invalid
		}
		layout[i] = bankChunk{at, size}
		at += size
	}
	bkhd, didx, data, hirc := layout[0], layout[1], layout[2], layout[3]
	if at != len(blob) || bkhd.size < 12 || u32(blob[bkhd.start:]) != 134 ||
		didx.size%12 != 0 || data.start%16 != 0 || hirc.size < 4 {
		return nil, invalid
	}
	type item struct {
		media               uint32
		offset, size, index int
	}
	media := make([]item, 0, didx.size/12)
	seen := make(map[uint32]bool)
	for i := didx.start; i < didx.start+didx.size; i += 12 {
		id, offset, size := u32(blob[i:]), int(u32(blob[i+4:])), int(u32(blob[i+8:]))
		if seen[id] || offset%16 != 0 || offset > data.size || size > data.size-offset {
			return nil, invalid
		}
		seen[id] = true
		media = append(media, item{id, offset, size, i})
	}
	for id := range edits {
		if !seen[id] {
			return nil, invalid
		}
	}
	sort.Slice(media, func(i, j int) bool { return media[i].offset < media[j].offset })
	output := make([]byte, data.start, len(blob))
	copy(output, blob)
	originalSizes := make(map[uint32]int)
	for _, item := range media {
		audio := blob[data.start+item.offset : data.start+item.offset+item.size]
		if replacement, ok := edits[item.media]; ok {
			originalSizes[item.media] = item.size
			audio = replacement
		}
		padding := (16 - (len(output)-data.start)%16) % 16
		output = append(output, make([]byte, padding)...)
		put(output[item.index+4:], uint32(len(output)-data.start))
		put(output[item.index+8:], uint32(len(audio)))
		output = append(output, audio...)
	}
	put(output[data.start-4:], uint32(len(output)-data.start))
	output = append(output, blob[hirc.start-8:]...)
	hircStart := len(output) - hirc.size
	at = hircStart + 4
	patched := make(map[uint32]bool)
	for count := u32(output[hircStart:]); count > 0; count-- {
		if len(output)-at < 9 {
			return nil, invalid
		}
		kind, size := output[at], int(u32(output[at+1:]))
		if size < 4 || size > len(output)-at-5 {
			return nil, invalid
		}
		payload := at + 9
		if kind == 2 {
			if size < 17 {
				return nil, invalid
			}
			id := u32(output[payload+5:])
			if audio, ok := edits[id]; ok {
				if output[payload+4] != 0 || int(u32(output[payload+9:])) != originalSizes[id] {
					return nil, invalid
				}
				put(output[payload+9:], uint32(len(audio)))
				patched[id] = true
			}
		}
		at += 5 + size
	}
	if at != len(output) || len(patched) != len(edits) {
		return nil, invalid
	}
	return output, nil
}
