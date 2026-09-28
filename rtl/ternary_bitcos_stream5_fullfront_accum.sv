// Full five-position BITCOS compressed-stream row accumulator.
//
// Unlike ternary_bitcos_stream5_accum, this wrapper accepts byte-packed
// presence storage directly. It therefore includes both:
//   1. presence-stream byte alignment, and
//   2. variable-rate compact-sign byte alignment.
//
// This wrapper includes the bitmap/sign byte-alignment front end used in the
// one-byte/cycle comparison with the five-trit streaming baseline.
module ternary_bitcos_stream5_fullfront_accum #(
    parameter int ACT_W = 8,
    parameter int ACC_W = 24
) (
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    start,
    input  logic [2:0]              initial_presence_offset,
    input  logic [2:0]              initial_sign_offset,
    input  logic                    valid,
    input  logic                    last,
    input  logic [5*ACT_W-1:0]      activations,
    input  logic [7:0]              current_presence_byte,
    input  logic [7:0]              next_presence_byte,
    input  logic [7:0]              current_sign_byte,
    input  logic [7:0]              next_sign_byte,
    output logic                    advance_presence_byte,
    output logic                    advance_sign_byte,
    output logic [2:0]              presence_offset,
    output logic [2:0]              sign_offset,
    output logic signed [ACC_W-1:0] dot,
    output logic                    done
);
    logic [4:0] presence;

    bitcos_presence5_bytecursor presence_cursor (
        .clk(clk),
        .rst_n(rst_n),
        .start_block(start),
        .initial_offset(initial_presence_offset),
        .advance(valid),
        .current_presence_byte(current_presence_byte),
        .next_presence_byte(next_presence_byte),
        .presence(presence),
        .offset_state(presence_offset),
        .advance_presence_byte(advance_presence_byte)
    );

    ternary_bitcos_stream5_accum #(
        .ACT_W(ACT_W),
        .ACC_W(ACC_W)
    ) core (
        .clk(clk),
        .rst_n(rst_n),
        .start(start),
        .initial_sign_offset(initial_sign_offset),
        .valid(valid),
        .last(last),
        .activations(activations),
        .presence(presence),
        .current_sign_byte(current_sign_byte),
        .next_sign_byte(next_sign_byte),
        .advance_sign_byte(advance_sign_byte),
        .sign_offset(sign_offset),
        .dot(dot),
        .done(done)
    );
endmodule
